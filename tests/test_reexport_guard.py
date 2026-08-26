"""weather_markets.py must not re-export names from nws / climatology /
climate_indices at module scope.

Sibling of test_paths_bypass_guard.py, test_bare_os_replace_guard.py and
test_date_today_guard.py -- a structural guard for an invariant that is easy to
undo by accident and gives no signal when it is undone.

WHY THIS EXISTS. `from nws import nws_prob` at module scope binds a SEPARATE
object. Monkeypatching `nws.nws_prob` does not rebind it, so the name has two
patchable targets that can disagree, and a test aiming at the source module
silently gets the real function. That is not a theoretical concern here: it
cost a real investigation (df7cd97f). analyze_trade's section-5 obs override
was reached through weather_markets' own copy of get_live_observation while
_compute_persistence_prob's call-time import saw nws's, so the override kept
fetching NYC's live temperature and the model probability moved with the
weather until the >0.25 model-market gap gate tripped on some days and not
others.

Call-time imports inside a function body are deliberately ALLOWED: they
re-resolve from the source module on every call, so a patch is always seen.
Only the module-scope form freezes a copy, so only that form is rejected.
"""

import ast
import pathlib

import pytest

#: Modules whose names weather_markets must reach through the module object.
_GUARDED_MODULES = frozenset({"nws", "climatology", "climate_indices"})

#: Every name previously re-exported, kept as an explicit belt-and-braces list
#: so a regression is named rather than merely counted.
_FORMERLY_REEXPORTED = (
    "get_live_observation",
    "get_enso_index",
    "temperature_adjustment",
    "climatological_prob",
    "fetch_nbm_forecast",
    "nws_prob",
    "obs_prob",
)

_SOURCE = pathlib.Path(__file__).resolve().parent.parent / "weather_markets.py"


def _module_scope_reexports() -> list[tuple[int, str, str]]:
    """Return (lineno, module, name) for every module-scope `from M import N`
    where M is guarded. Function-body imports are skipped by construction:
    only ast.Module's direct children are walked."""
    tree = ast.parse(_SOURCE.read_text(encoding="utf-8"), filename=str(_SOURCE))
    found = []
    for node in tree.body:  # module scope ONLY, deliberately not ast.walk
        if isinstance(node, ast.ImportFrom) and node.module in _GUARDED_MODULES:
            for alias in node.names:
                found.append((node.lineno, node.module, alias.name))
    return found


def test_no_module_scope_reexports_from_the_guarded_modules():
    offenders = _module_scope_reexports()
    assert not offenders, (
        "weather_markets.py re-exports these at module scope, which gives each "
        'name a second patchable target that `monkeypatch.setattr("<module>.'
        '<name>", ...)` does not reach:\n'
        + "\n".join(
            f"  line {ln}: from {mod} import {name}  ->  use {mod}.{name}(...)"
            for ln, mod, name in offenders
        )
        + "\n\nImport the module instead and call through it. A `from ... import"
        " ...` inside a function body is fine; this guard only rejects module"
        " scope."
    )


@pytest.mark.parametrize("name", _FORMERLY_REEXPORTED)
def test_formerly_reexported_name_is_not_an_attribute(name):
    """AST catches the import even when the name is unused; this catches a
    binding created some other way (an assignment, a stray `setattr`)."""
    import weather_markets

    assert not hasattr(weather_markets, name), (
        f"weather_markets.{name} exists again. Tests patch "
        f"the source module for this name, so a second binding here is "
        f"invisible to them -- see this module's docstring for what that cost."
    )


def test_the_guard_can_actually_fail():
    """Positive control. Without this, both tests above would pass just as
    happily if _GUARDED_MODULES were empty or the parse silently returned
    nothing."""
    tree = ast.parse(
        "from nws import nws_prob\n"
        "def f():\n"
        "    from nws import obs_prob\n"
        "    return obs_prob\n"
    )
    module_scope = [
        (n.module, a.name)
        for n in tree.body
        if isinstance(n, ast.ImportFrom) and n.module in _GUARDED_MODULES
        for a in n.names
    ]
    # The module-scope one is caught...
    assert module_scope == [("nws", "nws_prob")]
    # ...and the function-body one is deliberately NOT, which is the whole
    # distinction this guard rests on.
    assert all(name != "obs_prob" for _, name in module_scope)


def test_guarded_modules_are_the_ones_weather_markets_actually_imports():
    """Keeps the allowlist honest: if weather_markets stops importing one of
    these as a module, the guard for it has quietly become dead weight."""
    import weather_markets

    for mod in _GUARDED_MODULES:
        assert any(
            getattr(weather_markets, attr, None) is not None
            and getattr(getattr(weather_markets, attr), "__name__", None) == mod
            for attr in dir(weather_markets)
        ), f"weather_markets no longer holds a module object for {mod}"
