r"""Automated guard against orphaned functions in paper.py/tracker.py/weather_markets.py.

Part (b) of the config-divergence/dead-code guard (see
tests/test_config_divergence_guard.py for part (a), inert BotConfig fields).
That guard caught config knobs that look wired but aren't; this one catches
the sibling shape at the function level — a fully-implemented function with
zero callers anywhere, which happens when a feature gets superseded (see the
2026-07-12 removals: slippage_kelly_scale, is_weather_market,
_fetch_ensemble_members_historical were all replaced by a different approach
elsewhere, leaving the old implementation orphaned but never deleted) or
half-shipped (paper.undo_last_trade had real test coverage but no CLI/
dashboard entry point until this same date).

Two distinct dead-code shapes, because the fix differs:
  - FULLY DEAD: no reference anywhere, not even in tests. Delete it.
  - TESTED, NO PRODUCTION CALL SITE: real test coverage exists, but nothing
    in production code (outside tests/) ever calls it. Either wire it into a
    real call site, or delete it (and its now-pointless tests) if the
    feature was abandoned.

A third bucket, POSSIBLE DYNAMIC DISPATCH, is tracked but never asserted on:
a function name that appears as a bare string literal in production code
(e.g. web_app.py's `getattr(tracker, fn_name)()` analytics-panel dispatch
loop) may be called indirectly in a way this regex-based scan can't prove
one way or the other. Flagging it as dead would be a false positive (see
tracker.get_model_calibration_buckets, caught exactly this way during this
guard's construction) -- surfacing it for a human to check beats asserting
on a guess.

This scan is deliberately simple (regex over source text, not a full static
call-graph), matching test_config_divergence_guard.py's approach. It has two
codebase-specific wrinkles the implementation below handles:
  1. This project's dominant style for function-local cross-module imports
     is `from module import name as _name`, so a raw `\bname\s*\(` search
     alone would miss the overwhelming majority of real call sites.
  2. A full-line `#` comment that merely DISCUSSES a function -- e.g.
     "# ...and get_unselected_bias() always returned 0.0" -- matches the
     same call pattern as a real call, producing a false negative. Found
     live: tracker.get_unselected_bias read as "has a caller" for exactly
     this reason until comment-stripping was added.

This scan's first run (2026-07-12) surfaced 20 functions with no real call
site (the 4 originally-known candidates plus 16 more). All 20 got a real
per-function wire-up-or-delete decision that same session (see backlog.txt)
-- 3 were deliberately kept unwired (each has its own in-code comment citing
a real, unmet prerequisite; see _DEAD_CODE_ALLOWLIST below), the rest were
either wired into a real call site or deleted as superseded by a different
approach that was already live. This allowlist is expected to stay small
going forward -- a large allowlist growing back would mean this guard isn't
doing its job.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
_TARGET_FILES = ["paper.py", "tracker.py", "weather_markets.py"]


def _module_level_funcs(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and not node.name.startswith("__")
    ]


def _strip_def_line(src: str, name: str) -> str:
    """Remove `def name(...)` so a function's own definition doesn't count as
    a self-reference when scanning its own defining file."""
    pattern = re.compile(
        rf"^\s*(async\s+)?def\s+{re.escape(name)}\s*\(.*$", re.MULTILINE
    )
    return pattern.sub("", src)


def _strip_full_comment_lines(src: str) -> str:
    """Remove lines that are entirely a `#` comment (leading whitespace then
    `#`) before searching for calls. Without this, a full-line comment that
    merely DISCUSSES a function -- e.g. "# ...and get_unselected_bias()
    always returned 0.0" -- matches `\\bname\\s*\\(` exactly like a real call,
    producing a false negative (a genuinely dead function reads as having a
    caller). Only strips whole-comment lines, not trailing inline comments on
    a code line, to avoid touching string literals on real code."""
    pattern = re.compile(r"^\s*#.*$", re.MULTILINE)
    return pattern.sub("", src)


def _called_in(src: str, name: str) -> bool:
    """True if `name` -- or an import alias of it, e.g. `import name as
    _name` -- is directly called anywhere in src."""
    src = _strip_full_comment_lines(src)
    call_pat = re.compile(rf"\b{re.escape(name)}\s*\(")
    if call_pat.search(src):
        return True
    for alias in re.findall(rf"\b{re.escape(name)}\s+as\s+(\w+)", src):
        if re.search(rf"\b{re.escape(alias)}\s*\(", src):
            return True
    return False


def _string_referenced_in(src: str, name: str) -> bool:
    """True if `name` appears as a quoted string literal -- e.g. a
    getattr(module, "name")() dynamic-dispatch table. Weaker than a direct
    call: doesn't prove reachability, but rules out confidently calling the
    function dead without a human checking the dispatch site."""
    return bool(re.search(rf'["\']{re.escape(name)}["\']', src))


def _scan() -> tuple[
    list[tuple[str, str]], list[tuple[str, str]], list[tuple[str, str]]
]:
    """Returns (fully_dead, tested_unreachable, possible_dynamic) as
    (filename, function_name) pairs."""
    prod_files = sorted(_REPO_ROOT.glob("*.py"))
    test_files = sorted((_REPO_ROOT / "tests").glob("*.py"))
    prod_src = {p: p.read_text(encoding="utf-8") for p in prod_files}
    test_src = {p: p.read_text(encoding="utf-8") for p in test_files}

    fully_dead = []
    tested_unreachable = []
    possible_dynamic = []

    for tf in _TARGET_FILES:
        path = _REPO_ROOT / tf
        for name in _module_level_funcs(path):
            prod_call = False
            prod_string = False
            for p, src in prod_src.items():
                search_src = _strip_def_line(src, name) if p == path else src
                if _called_in(search_src, name):
                    prod_call = True
                    break
                if _string_referenced_in(search_src, name):
                    prod_string = True

            if prod_call:
                continue
            if prod_string:
                possible_dynamic.append((tf, name))
                continue

            if any(_called_in(src, name) for src in test_src.values()):
                tested_unreachable.append((tf, name))
            else:
                fully_dead.append((tf, name))

    return fully_dead, tested_unreachable, possible_dynamic


# (filename, function_name) -> reason. Every currently-known dead/orphaned
# function must be listed here with a concrete reason, or the scan test
# below fails -- exactly the _DEAD_FIELD_ALLOWLIST pattern from
# test_config_divergence_guard.py, one level down (functions, not config
# fields). A NEW function landing in either dead-code bucket without an
# entry here is a signal worth a second look before merging, not something
# to silently allowlist.
_DEAD_CODE_ALLOWLIST: dict[tuple[str, str], str] = {
    # -- All 3 entries below are TESTED, NO PROD CALL SITE, and deliberately
    # left unwired: each has its own in-code comment (not this session's
    # guess) explaining a real prerequisite that hasn't happened yet. Wiring
    # any of these in without that prerequisite would be a live probability/
    # forecast-behavior change with no way to validate it's actually correct
    # -- re-verified 2026-07-12 while triaging the 20 functions this scan's
    # first run surfaced (see backlog.txt); all other candidates from that
    # run were individually wired up or deleted as superseded, not left here.
    ("tracker.py", "get_unselected_bias"): (
        "TESTED, NO PROD CALL SITE -- own docstring says it reflects a "
        "selection-biased ~2% subset of the real untraded population and "
        "explicitly says 'Build that sweep before wiring this into anything "
        "real' (a ~2,000-extra-Kalshi-API-call settlement sweep, not built)"
    ),
    ("weather_markets.py", "_fetch_hrrr_temp"): (
        "TESTED, NO PROD CALL SITE -- own comment says 'This is a standalone "
        "utility; it is NOT wired into analyze_trade yet -- that happens "
        "once HRRR data has been validated against settled same-day trades' "
        "(that validation hasn't happened)"
    ),
    ("weather_markets.py", "censoring_correction"): (
        "TESTED, NO PROD CALL SITE -- correctly implemented per its #23 spec "
        "(shrink toward 0.5 when >1% of ensemble members are exactly 0/1), "
        "but wiring it into the live forecast-probability pipeline is a real "
        "behavior change needing backtesting to confirm it actually improves "
        "calibration, not something to do blind"
    ),
}


def test_no_new_dead_code_outside_allowlist():
    """Fails if a function in paper.py/tracker.py/weather_markets.py has zero
    callers (fully dead, or tested but with no production call site) and
    isn't already in _DEAD_CODE_ALLOWLIST -- catches new dead code landing
    silently, same shape as test_config_divergence_guard.py's field check.
    """
    fully_dead, tested_unreachable, _possible_dynamic = _scan()
    unexplained = [
        (tf, name, "FULLY DEAD")
        for tf, name in fully_dead
        if (tf, name) not in _DEAD_CODE_ALLOWLIST
    ] + [
        (tf, name, "TESTED, NO PROD CALL SITE")
        for tf, name in tested_unreachable
        if (tf, name) not in _DEAD_CODE_ALLOWLIST
    ]
    assert not unexplained, (
        "Function(s) with no real call site and no entry in "
        "_DEAD_CODE_ALLOWLIST -- wire it to a real call site, delete it, or "
        "add it to the allowlist with a concrete reason:\n"
        + "\n".join(f"  - {tf}:{name} ({cat})" for tf, name, cat in unexplained)
    )


def test_dead_code_allowlist_has_no_stale_entries():
    """Inverse check: every allowlisted (file, function) pair must still be
    an actual module-level function in that file (catches a rename/deletion
    leaving a stale, misleading allowlist entry behind)."""
    current: set[tuple[str, str]] = set()
    for tf in _TARGET_FILES:
        for name in _module_level_funcs(_REPO_ROOT / tf):
            current.add((tf, name))
    stale = [key for key in _DEAD_CODE_ALLOWLIST if key not in current]
    assert not stale, (
        f"Stale dead-code allowlist entries, function no longer exists: {stale}"
    )
