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


def _bare_called_in(src: str, name: str) -> bool:
    """True if the bare, unaliased `name(` is directly called in src."""
    src = _strip_full_comment_lines(src)
    return bool(re.search(rf"\b{re.escape(name)}\s*\(", src))


def _alias_called_in(src: str, name: str) -> bool:
    """True if an import alias of `name` (`from module import name as
    alias`) is called in src."""
    src = _strip_full_comment_lines(src)
    for alias in re.findall(rf"\b{re.escape(name)}\s+as\s+(\w+)", src):
        if re.search(rf"\b{re.escape(alias)}\s*\(", src):
            return True
    return False


def _called_in(src: str, name: str) -> bool:
    """True if `name` -- or an import alias of it, e.g. `import name as
    _name` -- is directly called anywhere in src."""
    return _bare_called_in(src, name) or _alias_called_in(src, name)


def _string_referenced_in(src: str, name: str) -> bool:
    """True if `name` appears as a quoted string literal -- e.g. a
    getattr(module, "name")() dynamic-dispatch table. Weaker than a direct
    call: doesn't prove reachability, but rules out confidently calling the
    function dead without a human checking the dispatch site."""
    return bool(re.search(rf'["\']{re.escape(name)}["\']', src))


def _resolve_prod_evidence(
    name: str,
    defining_path: Path,
    prod_src: dict[Path, str],
    funcs_by_file: dict[Path, set[str]],
) -> tuple[bool, bool]:
    """Return (has_real_call, has_string_reference) for `name` (a module-level
    function defined in defining_path) across every file in prod_src.

    Resolves a same-name collision across files: if another file `p`
    independently defines its own module-level function also called `name`
    (e.g. order_executor._current_forecast_cycle vs
    weather_markets._current_forecast_cycle -- see backlog.txt "TWO
    FUNCTIONS NAMED _current_forecast_cycle"), a bare `name(` call inside
    `p` resolves to p's OWN definition at runtime, not defining_path's --
    counting it as evidence gives a dead function in defining_path a false
    "has a caller" reading. Only an explicit alias import of `name` FROM
    defining_path's module (`from module import name as alias`, then
    `alias(...)`) still proves a real cross-file call in that case; a plain
    call in a file that doesn't define its own colliding `name` is
    unambiguous and still counted as before.
    """
    prod_call = False
    prod_string = False
    for p, src in prod_src.items():
        if p == defining_path:
            search_src = _strip_def_line(src, name)
            called = _called_in(search_src, name)
        elif name in funcs_by_file.get(p, set()):
            # p's own bare `name(` calls are self-references (see docstring
            # above) -- no need to strip p's def line, since only the alias
            # check runs here and a `def name(` line can't match it.
            search_src = src
            called = _alias_called_in(search_src, name)
        else:
            search_src = src
            called = _called_in(search_src, name)

        if called:
            prod_call = True
            break
        if _string_referenced_in(search_src, name):
            prod_string = True
    return prod_call, prod_string


def _scan() -> tuple[
    list[tuple[str, str]], list[tuple[str, str]], list[tuple[str, str]]
]:
    """Returns (fully_dead, tested_unreachable, possible_dynamic) as
    (filename, function_name) pairs."""
    prod_files = sorted(_REPO_ROOT.glob("*.py"))
    test_files = sorted((_REPO_ROOT / "tests").glob("*.py"))
    prod_src = {p: p.read_text(encoding="utf-8") for p in prod_files}
    test_src = {p: p.read_text(encoding="utf-8") for p in test_files}
    # Precomputed once so per-name collision checks don't re-parse every
    # production file's AST for every candidate function.
    funcs_by_file = {p: set(_module_level_funcs(p)) for p in prod_files}

    fully_dead = []
    tested_unreachable = []
    possible_dynamic = []

    for tf in _TARGET_FILES:
        path = _REPO_ROOT / tf
        for name in _module_level_funcs(path):
            prod_call, prod_string = _resolve_prod_evidence(
                name, path, prod_src, funcs_by_file
            )

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
    # -- Every entry below is TESTED, NO PROD CALL SITE, and deliberately
    # left unwired: each cites either its own docstring/in-code comment or
    # the relevant backlog.txt entry (not this session's guess) explaining a
    # real prerequisite that hasn't happened yet. Wiring any of these in
    # without that prerequisite would be a live probability/forecast-
    # behavior change with no way to validate it's actually correct
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
    ("tracker.py", "get_price_history"): (
        "TESTED, NO PROD CALL SITE -- read accessor for the price_history "
        "table added 2026-07-12 (candlestick capture, see backlog.txt). The "
        "capture side ships now; the entry-timing/adverse-selection analysis "
        "that would call this is explicitly deferred until the maker-"
        "execution backlog work is picked up (candles only accumulate from "
        "when capture ships, so there's nothing to analyze yet regardless)"
    ),
    ("tracker.py", "get_trade_history"): (
        "TESTED, NO PROD CALL SITE -- read accessor for the trade_history "
        "table added 2026-07-19 (PUBLIC TRADES REST BACKFILL, see "
        "backlog.txt). Same shape as get_price_history above: the capture "
        "side (log_trades, wired into sync_outcomes) ships now; the "
        "adverse-selection/informed-flow analysis that would call this is "
        "explicitly deferred, paired with get_price_history's own "
        "enablement trigger -- both tables start empty and only accumulate "
        "from markets settling after this ships"
    ),
    ("tracker.py", "get_regional_recent_bias"): (
        "TESTED, NO PROD CALL SITE -- correlation-weighted mean forecast "
        "error of correlated cities' recent settlements (backlog.txt "
        "CROSS-CITY RECENT-ERROR POOLING, function itself shipped 2026-07-23; "
        "not called from any production path yet, log-only in the sense that "
        "the backlog entry frames this as the log/measurement step before a "
        "forecast-lean consumer exists). Wiring the result into an actual "
        "forecast lean is explicitly deferred until more settled data exists "
        "to validate it against, same shape as get_unselected_bias/"
        "censoring_correction above -- not something to wire in blind"
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


class TestSameNameCollisionResolution:
    """backlog.txt "TWO FUNCTIONS NAMED _current_forecast_cycle" -- this scan
    used to attribute a same-named function's bare calls in one file to a
    completely different function of the same name defined in another file
    (order_executor.py's own 5 calls to its own _current_forecast_cycle made
    weather_markets.py's dead, same-named copy look reachable). Synthetic
    in-memory sources so these stay meaningful regardless of real repo
    content -- same pattern as test_date_today_guard.py's guard tests."""

    def test_same_name_collision_in_another_file_is_not_counted_as_a_call(self):
        defining_path = Path("weather_markets.py")
        other_path = Path("order_executor.py")
        prod_src = {
            defining_path: "def _current_forecast_cycle():\n    return '12z'\n",
            other_path: (
                "def _current_forecast_cycle():\n"
                "    return '2026-01-01_00z'\n"
                "\n"
                "def foo():\n"
                "    return _current_forecast_cycle()\n"
                "\n"
                "def bar():\n"
                "    return _current_forecast_cycle()\n"
            ),
        }
        funcs_by_file = {
            defining_path: {"_current_forecast_cycle"},
            other_path: {"_current_forecast_cycle", "foo", "bar"},
        }
        prod_call, prod_string = _resolve_prod_evidence(
            "_current_forecast_cycle", defining_path, prod_src, funcs_by_file
        )
        assert prod_call is False, (
            "a same-named function's own self-calls in another file must "
            "not count as evidence that defining_path's function is called"
        )
        assert prod_string is False

    def test_real_cross_file_alias_call_is_still_counted(self):
        """Baseline sanity check: the normal (no collision) alias-import
        cross-file call path must still work after the collision fix."""
        defining_path = Path("module_a.py")
        other_path = Path("module_b.py")
        prod_src = {
            defining_path: "def helper():\n    return 1\n",
            other_path: (
                "from module_a import helper as _helper\n"
                "\n"
                "def use_it():\n"
                "    return _helper()\n"
            ),
        }
        funcs_by_file = {
            defining_path: {"helper"},
            other_path: {"use_it"},
        }
        prod_call, _ = _resolve_prod_evidence(
            "helper", defining_path, prod_src, funcs_by_file
        )
        assert prod_call is True

    def test_real_cross_file_bare_call_with_no_collision_is_still_counted(self):
        """No collision (module_c doesn't define its own `helper`) -- a
        plain, unaliased import-and-call must still count, exactly as
        before the collision fix."""
        defining_path = Path("module_a.py")
        other_path = Path("module_c.py")
        prod_src = {
            defining_path: "def helper():\n    return 1\n",
            other_path: ("from module_a import helper\n\n\nhelper()\n"),
        }
        funcs_by_file = {
            defining_path: {"helper"},
            other_path: set(),
        }
        prod_call, _ = _resolve_prod_evidence(
            "helper", defining_path, prod_src, funcs_by_file
        )
        assert prod_call is True

    def test_collision_with_explicit_alias_import_still_counts(self):
        """Mutation-proof pair to the first test: even when another file
        defines its OWN colliding `name`, an explicit alias import of the
        real target function must still be detected as a genuine call --
        proving the collision branch only suppresses the ambiguous bare
        call, not real cross-file evidence."""
        defining_path = Path("weather_markets.py")
        other_path = Path("order_executor.py")
        prod_src = {
            defining_path: "def _current_forecast_cycle():\n    return '12z'\n",
            other_path: (
                "from weather_markets import _current_forecast_cycle as _wm_cycle\n"
                "\n"
                "def _current_forecast_cycle():\n"
                "    return '2026-01-01_00z'\n"
                "\n"
                "def foo():\n"
                "    return _current_forecast_cycle()\n"
                "\n"
                "def bar():\n"
                "    return _wm_cycle()\n"
            ),
        }
        funcs_by_file = {
            defining_path: {"_current_forecast_cycle"},
            other_path: {"_current_forecast_cycle", "foo", "bar"},
        }
        prod_call, _ = _resolve_prod_evidence(
            "_current_forecast_cycle", defining_path, prod_src, funcs_by_file
        )
        assert prod_call is True
