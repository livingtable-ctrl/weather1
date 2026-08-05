r"""Automated guard against the paths.py-bypass anti-pattern reappearing.

backlog.txt "~13 NON-SAFETY-CRITICAL FILES STILL BYPASS paths.py -- WORKTREE
CRON RUNS SILENTLY HIT A STALE LOCAL data/ CACHE" (resolved 2026-08-05,
following on from f94a44b's earlier safety-critical-only pass): any module
that constructs `Path(__file__).parent / "data" / ...` (or the even worse
cwd-relative `Path("data/...")`) locally, instead of importing the
equivalent constant from paths.py, silently resolves to that *worktree's
own* throwaway data/ directory when run from a git worktree (this project's
standard dev workflow) rather than the main clone's real state -- see
paths.py's own module docstring for why `safe_io.project_root()` is needed
instead of `Path(__file__).parent`.

This scan is deliberately simple (regex over source text), matching
test_dead_code_scan.py's / test_config_divergence_guard.py's own approach.
It scans EVERY *.py file in the repo (recursive, including tests/) except
paths.py itself (the single source of truth these constants live in, where
the literal pattern legitimately appears in constant definitions and the
module docstring) and this guard file. tests/ is deliberately included, not
excluded: a first draft of this guard skipped tests/ on the theory that
tests only use tmp_path-based Path() construction, but a broadened scan
during this guard's own opus review found a genuine, live instance --
tests/test_phase2_batch_c.py's `_DATA_DIR = Path(__file__).parent.parent /
"data"` was reading the *worktree's* stale weight files instead of the main
clone's real ones, the exact symptom class this guard exists to catch,
hiding in a test file. Fixed in the same commit as this guard (routed
through `paths.DATA_DIR` like everything else).

Known limitation: this is a source-text regex, not a static call graph, so
it cannot catch an indirect two-step construction split across statements
(e.g. `_HERE = Path(__file__).parent` on one line, `_HERE / "data"` on a
later one) -- matching test_dead_code_scan.py's own disclosed limitation
for the same reason (regex over source text beats a full call-graph in
simplicity, at the cost of this kind of indirection).
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
_SELF = Path(__file__)

# Matches:
#   - Path(__file__)<anything up to 30 chars>.parent(s)[optional [n]] / "data"
#     -- covers .parent, .parent.parent, .resolve().parent, .parents[0],
#     .absolute().parent, and the fully-qualified pathlib.Path(...) / the
#     __import__("pathlib").Path(...) form (utils.py's old style), since
#     none of those prefix forms change what precedes "Path(__file__)".
#   - Path(<optional r/f string prefix><quote><optional ./><data><quote or
#     more path>) -- covers the cwd-relative form in all of its quoting
#     variants: Path("data/x"), Path("data"), Path("./data/x"),
#     Path(f"data/{name}"), Path(r"data/x").
_BYPASS_PATTERN = re.compile(
    r'Path\(__file__\)[^\n]{0,30}\.parents?(?:\[\d+\])?\s*/\s*[\'"]data[\'"]'
    r'|Path\(\s*[rf]{0,2}[\'"]\.?/?data(?:[\'"]|/)'
)

# Deliberately empty. A genuinely-inert exception should be documented here
# (keyed by path relative to the repo root, since a recursive scan can have
# same-named files in different directories) with a comment explaining why
# it can't route through paths.py, not added silently -- this allowlist is
# expected to stay empty going forward; if it grows, that's a signal this
# guard isn't doing its job. Value is (expected match count, reason), not
# just a reason string: a bare "skip this whole file" entry would blind the
# guard to every OTHER bypass added later to the same file, not just the
# allowlisted one -- keying on the exact count means a new, unallowlisted
# occurrence in an already-allowlisted file still fails loudly.
_ALLOWLIST: dict[str, tuple[int, str]] = {}


def _all_source_files() -> list[Path]:
    result = []
    for p in _REPO_ROOT.rglob("*.py"):
        if not p.is_file() or p in (_REPO_ROOT / "paths.py", _SELF):
            continue
        rel_parts = p.relative_to(_REPO_ROOT).parts
        # Skip hidden dirs (.git, .mypy_cache, .pytest_cache, .ruff_cache,
        # .superpowers, ...) and __pycache__ -- none of the repo's real
        # source lives there, confirmed via a find sweep when this guard
        # was written; a real source file should never need to sit under a
        # dot-directory or __pycache__. Checked against the path RELATIVE
        # to _REPO_ROOT, not the absolute path -- this repo is commonly
        # checked out under a dot-directory itself (e.g. a worktree under
        # `.claude/worktrees/...`), and checking the absolute path's parts
        # would silently exclude every file in that checkout.
        if any(part.startswith(".") or part == "__pycache__" for part in rel_parts):
            continue
        result.append(p)
    return sorted(result)


def test_no_new_paths_py_bypass_sites():
    """No *.py file anywhere in the repo should construct its own data/
    path locally.

    Mutation check: reverting any single one of this session's migrations
    (e.g. restoring circuit_breaker.py's old
    `_CB_STATE_PATH = Path(__file__).parent / "data" / ".cb_state.json"`)
    makes this test fail, since the regex matches the exact anti-pattern
    each of those local assignments used. Also mutation-checked against
    tests/test_phase2_batch_c.py's real pre-fix line
    (`_DATA_DIR = Path(__file__).parent.parent / "data"`) -- restoring it
    fails this test too.
    """
    offenders: dict[str, list[str]] = {}
    for path in _all_source_files():
        rel = path.relative_to(_REPO_ROOT).as_posix()
        src = path.read_text(encoding="utf-8")
        matches = _BYPASS_PATTERN.findall(src)
        expected_count, _reason = _ALLOWLIST.get(rel, (0, ""))
        if len(matches) != expected_count:
            offenders[rel] = matches

    assert not offenders, (
        "Found paths.py-bypass anti-pattern (Path(__file__).parent/'data' or "
        "Path('data/...')) outside paths.py, or an allowlisted file's match "
        "count changed -- add the missing constant to paths.py and import it "
        "instead, or document/update a real exception in _ALLOWLIST above:\n"
        + "\n".join(f"  {name}: {ms}" for name, ms in offenders.items())
    )


def test_allowlist_entries_still_exist_and_are_justified():
    """Every _ALLOWLIST entry must name a real file, a positive expected
    count, and a non-empty reason.

    Prevents a stale allowlist entry (the file was migrated later but the
    entry never removed) from silently masking a real regression the way an
    empty-string, missing-file, or zero-count entry would.
    """
    for rel_path, (expected_count, reason) in _ALLOWLIST.items():
        assert (_REPO_ROOT / rel_path).is_file(), (
            f"_ALLOWLIST references {rel_path!r}, which doesn't exist"
        )
        assert expected_count > 0, (
            f"_ALLOWLIST entry for {rel_path!r} has a non-positive expected "
            "count -- remove the entry entirely instead of allowlisting zero "
            "occurrences"
        )
        assert reason.strip(), f"_ALLOWLIST entry for {rel_path!r} has no reason"
