"""G5: the writer is shadow-only by construction.

Walks the call graph out of cron._log_price_recal_picks over the repo's own AST
and asserts it reaches neither a network client nor an order-placement path.
Structural, not a docstring reading -- the exit-rule log's first version was
documented as observational while fetching its own quotes.

NEGATIVE ASSERTION, so it carries its own positive control: run with
--self-test it plants a call to a forbidden symbol into the analysed source and
must report the violation. A checker that cannot fail proves nothing about the
code it passes.
"""

from __future__ import annotations

import ast
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
ENTRY_MODULE = "cron"
ENTRY_FUNC = "_log_price_recal_picks"

# Names that mean "this touched the network or placed an order". Matched on the
# attribute/function NAME, so cron.foo(), client.foo() and a bare foo() all hit.
FORBIDDEN = {
    # order placement
    "place_order",
    "place_maker_order",
    "place_paper_order",
    "_place_live_order",
    "_auto_place_trades",
    "amend_order",
    "cancel_order",
    # network transport
    "_get",
    "_post",
    "_delete",
    "_request",
    "_paginate_get",
    "urlopen",
    "urlretrieve",
    # the shared circuit breaker, whose is_open() is a mutator
    "is_open",
    "record_success",
    "record_failure",
}
# Bare "get"/"post" are NOT in the set above: dict.get() is everywhere and a
# name-only match on it flags every well-behaved function in the repo. Network
# transport is caught two ways instead -- by the specific client method names
# above, and by any attribute call on one of these receivers.
NET_RECEIVERS = {"requests", "httpx", "urllib", "urllib3", "session", "client",
                 "_client", "http", "conn"}
NET_VERBS = {"get", "post", "put", "patch", "delete", "head", "request", "send"}

# Modules whose functions are followed. Anything outside this set is a leaf: it
# is reported as UNRESOLVED rather than silently assumed safe.
FOLLOW = {"cron", "weather_markets", "utils", "positions", "tracker"}


def load(mod: str) -> ast.Module | None:
    path = ROOT / f"{mod}.py"
    if not path.exists():
        return None
    return ast.parse(path.read_text(encoding="utf-8", errors="replace"), str(path))


def functions(tree: ast.Module) -> dict[str, ast.AST]:
    out: dict[str, ast.AST] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.setdefault(node.name, node)
    return out


def called_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Name):
                names.add(f.id)
            elif isinstance(f, ast.Attribute):
                names.add(f.attr)
                recv = f.value
                if (
                    isinstance(recv, ast.Name)
                    and recv.id.lower() in NET_RECEIVERS
                    and f.attr in NET_VERBS
                ):
                    names.add(f"{recv.id}.{f.attr}")
    return names


def analyse(inject: str | None = None) -> tuple[list[str], list[str]]:
    trees = {m: load(m) for m in FOLLOW}
    src = (ROOT / f"{ENTRY_MODULE}.py").read_text(encoding="utf-8", errors="replace")
    if inject:
        # Positive control: plant the forbidden call inside the entry function.
        marker = "    now_iso = datetime.now(UTC).isoformat()"
        assert marker in src, "positive-control anchor moved; control is broken"
        src = src.replace(marker, marker + f"\n    {inject}", 1)
        trees[ENTRY_MODULE] = ast.parse(src)

    fns = {m: functions(t) for m, t in trees.items() if t is not None}
    violations: list[str] = []
    unresolved: set[str] = set()
    seen: set[tuple[str, str]] = set()
    stack = [(ENTRY_MODULE, ENTRY_FUNC)]
    while stack:
        mod, name = stack.pop()
        if (mod, name) in seen:
            continue
        seen.add((mod, name))
        node = fns.get(mod, {}).get(name)
        if node is None:
            continue
        for callee in sorted(called_names(node)):
            if callee in FORBIDDEN or (
                "." in callee
                and callee.split(".")[0].lower() in NET_RECEIVERS
                and callee.split(".")[1] in NET_VERBS
            ):
                violations.append(f"{mod}.{name} -> {callee}")
                continue
            hit = next((m for m in FOLLOW if callee in fns.get(m, {})), None)
            if hit:
                stack.append((hit, callee))
            else:
                unresolved.add(callee)
    return violations, sorted(unresolved)


if "--self-test" in sys.argv:
    v, _ = analyse(inject="_KalshiClient().place_order(1)")
    if not v:
        print("FAIL: positive control did NOT trip -- this checker cannot fail")
        sys.exit(1)
    print(f"positive control tripped as required: {v}")
    print("GATE_G5_SELFTEST_PASS")
    sys.exit(0)

violations, unresolved = analyse()
print(f"reachable functions walked: modules {sorted(FOLLOW)}")
print(f"unresolved leaf calls ({len(unresolved)}): {unresolved}")

# The control has to run in the same invocation the gate passes on, or the gate
# is trusting a property it never demonstrated.
ctrl, _ = analyse(inject="_KalshiClient().place_order(1)")
if not ctrl:
    print("FAIL: positive control did NOT trip -- this checker cannot fail")
    sys.exit(1)
print(f"positive control tripped: {ctrl}")

if violations:
    for v in violations:
        print(f"FAIL: shadow writer reaches a forbidden path: {v}")
    sys.exit(1)
print("GATE_G5_PASS")
