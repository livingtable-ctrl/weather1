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
# Round 1 added a second production entry point (the progress readout) that the
# walk did not cover. Both are walked now.
ENTRY_FUNCS = ("_log_price_recal_picks",)
ENTRY_FUNC = ENTRY_FUNCS[0]
EXTRA_ENTRIES = (
    ("tracker", "settle_price_recal_picks"),
    ("tracker", "get_price_recal_progress"),
)

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
NET_RECEIVERS = {
    "requests",
    "httpx",
    "urllib",
    "urllib3",
    "session",
    "client",
    "http",
    "conn",
    "socket",
    "subprocess",
    "aiohttp",
    "urlopen",
    "api",
    "transport",
}
NET_VERBS = {"get", "post", "put", "patch", "delete", "head", "request", "send"}

# Modules whose functions are followed. Anything outside this set is a leaf: it
# is reported as UNRESOLVED rather than silently assumed safe.
# A TUPLE, not a set: `next((m for m in FOLLOW if callee in fns[m]), None)`
# iterates it, and set iteration order varies with string-hash randomisation
# between runs -- so which definition of a same-named function got walked was
# nondeterministic.
FOLLOW = (
    "cron",
    "weather_markets",
    "utils",
    "positions",
    "tracker",
    "order_executor",
    "kalshi_client",
    "paper",
)

# Every call the walk cannot resolve to a followed module must appear here.
# An earlier version merely PRINTED the unresolved set and passed regardless,
# which is how it missed an aliased `import requests as rq; rq.get(...)`, an
# `httpx.Client().get(...)` (receiver is a Call, not a Name), a
# `self._session.get(...)` (receiver is an Attribute), a bare
# `from order_executor import submit_trade`, a raw socket and a subprocess curl.
# Failing closed on anything unrecognised is the only way a negative assertion
# means what its gate title says.
# `get` is deliberately NOT in ALLOWED_LEAVES. Round 2 drove
# `from requests import get; get(url)` at this checker and it passed, because
# the comment below correctly kept bare `get` out of FORBIDDEN (dict.get is
# everywhere) and then put it in the allowlist -- blinding the fail-closed path
# to the single likeliest network verb for a writer that "just refreshes a
# quote". `post`, `put` and `request` were all caught as unknown leaves; only
# `get` walked through. It is now allowed ONLY as an attribute call on a
# receiver the writer really uses.
DICT_GET_RECEIVERS = {
    "analysis",
    "enriched",
    "quote",
    "condition",
    "market",
    "a",
    "row",
    "r",
    "_prsl_prog",
    "progress",
    "kw",
    "opts",
    "d",
    "cfg",
    "os",
    "environ",
}
ALLOWED_LEAVES = {
    # builtins
    "abs",
    "all",
    "any",
    "bool",
    "callable",
    "dict",
    "enumerate",
    "float",
    "getattr",
    "hasattr",
    "int",
    "isinstance",
    "len",
    "list",
    "max",
    "min",
    "print",
    "range",
    "round",
    "set",
    "sorted",
    "str",
    "sum",
    "tuple",
    "zip",
    # stdlib used by the writer
    "append",
    "ceil",
    "close",
    "commit",
    "connect",
    "cursor",
    "date",
    "debug",
    "error",
    "exception",
    "execute",
    "executemany",
    "exp",
    "erf",
    "executescript",
    "fetchall",
    "fetchone",
    "fromisoformat",
    "info",
    "isoformat",
    "items",
    "keys",
    "log",
    "mkdir",
    "lower",
    "now",
    "replace",
    "rowcount",
    "split",
    "sqrt",
    "strip",
    "values",
    "warning",
    "Path",
    "total_seconds",
}


def load(mod: str) -> ast.Module | None:
    path = ROOT / f"{mod}.py"
    if not path.exists():
        return None
    return ast.parse(path.read_text(encoding="utf-8", errors="replace"), str(path))


def functions(tree: ast.Module) -> dict[str, ast.AST]:
    out: dict[str, ast.AST] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            out.setdefault(node.name, node)
    return out


def import_aliases(node: ast.AST) -> dict[str, str]:
    """Map local alias -> real symbol for imports made inside a function.

    `from tracker import init_db as _prsl_init_db` used to leave the walk
    staring at an unknown `_prsl_init_db`, which is precisely the aliased-import
    form that let a `import requests as rq; rq.get(...)` through. Resolving the
    alias means the walk follows the REAL symbol, so an alias can neither hide a
    forbidden name nor be waved through as an unknown leaf.
    """
    out: dict[str, str] = {}
    for n in ast.walk(node):
        if isinstance(n, ast.ImportFrom):
            for a in n.names:
                if a.asname:
                    out[a.asname] = a.name
        elif isinstance(n, ast.Import):
            for a in n.names:
                if a.asname:
                    out[a.asname] = a.name.split(".")[0]
    return out


def called_names(node: ast.AST) -> tuple[set[str], set[tuple[str, str]]]:
    """Return (bare call names, (receiver, attr) pairs for Name receivers).

    The pairs are kept SEPARATELY and unconditionally. An earlier version only
    recorded `receiver.attr` when the receiver literally matched a known network
    name, which meant an alias (`import requests as rq`) was never even a
    candidate for the check -- the one form the alias resolution exists for.
    """
    names: set[str] = set()
    pairs: set[tuple[str, str]] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Name):
                names.add(f.id)
            elif isinstance(f, ast.Attribute):
                if f.attr == "get":
                    # `.get(` is allowed ONLY on a receiver that is plainly a
                    # local mapping. Anything else -- including a bare imported
                    # `get` -- reaches the fail-closed path below.
                    if (
                        isinstance(f.value, ast.Name)
                        and f.value.id.lower().lstrip("_") in DICT_GET_RECEIVERS
                    ):
                        pass  # a dict lookup, not a request
                    else:
                        names.add("<unqualified-get>")
                else:
                    names.add(f.attr)
                if isinstance(f.value, ast.Name):
                    pairs.add((f.value.id, f.attr))
                elif isinstance(f.value, ast.Attribute):
                    # self._session.get(...) -- receiver is an Attribute
                    pairs.add((f.value.attr, f.attr))
                elif isinstance(f.value, ast.Call):
                    # httpx.Client().get(...) -- receiver is a Call
                    inner = f.value.func
                    head = (
                        inner.value.id
                        if isinstance(inner, ast.Attribute)
                        and isinstance(inner.value, ast.Name)
                        else getattr(inner, "id", "")
                    )
                    if head:
                        pairs.add((head, f.attr))
            else:
                # getattr(m, "place_order")(), H["k"](), L[0](), (lambda…)()  --
                # an entire node class that produced NO entry at all before, so
                # it was neither a violation nor an unresolved leaf. A gate whose
                # stated property is "fails closed on anything unrecognised" may
                # not silently exempt a whole dispatch form.
                names.add("<dynamic-dispatch>")
    return names, pairs


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
    # Module-level aliases as well as function-local ones: `import requests as
    # rq` at the top of a file is the commoner form, and reading only
    # function-local imports would leave exactly the hole this resolves.
    module_aliases = {
        m: import_aliases(tree) for m, tree in trees.items() if tree is not None
    }
    violations: list[str] = []
    unresolved: set[str] = set()
    seen: set[tuple[str, str]] = set()
    stack = [(ENTRY_MODULE, ENTRY_FUNC), *EXTRA_ENTRIES]
    while stack:
        mod, name = stack.pop()
        if (mod, name) in seen:
            continue
        seen.add((mod, name))
        node = fns.get(mod, {}).get(name)
        if node is None:
            continue
        aliases = dict(module_aliases.get(mod, {}))
        aliases.update(import_aliases(node))
        raw, pairs = called_names(node)
        resolved = {aliases.get(c, c) for c in raw}
        for head, verb in pairs:
            tgt = aliases.get(head, head)
            # lstrip("_"): `self._session.get(...)` yields a receiver of
            # `_session`, and listing every underscore variant by hand is how
            # the set goes stale.
            if tgt.lower().lstrip("_") in NET_RECEIVERS and verb in NET_VERBS:
                resolved.add(f"{tgt}.{verb}")
        for callee in sorted(resolved):
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
unknown = sorted(set(unresolved) - ALLOWED_LEAVES)
if unknown:
    for u in unknown:
        print(
            f"FAIL: unresolved call {u!r} is neither followed nor allowlisted "
            f"-- this gate fails closed, add it to ALLOWED_LEAVES only after "
            f"confirming it cannot reach the network or an order"
        )
    sys.exit(1)

# The control has to run in the same invocation the gate passes on, or the gate
# is trusting a property it never demonstrated.
# SIX controls, not one. A single place_order() control only ever proved the
# FORBIDDEN-name path worked; it said nothing about the forms that actually got
# through. Each of these was a real miss before ALLOWED_LEAVES existed.
CONTROLS = [
    ("hardcoded order name", "_KalshiClient().place_order(1)"),
    ("aliased import", "import requests as rq; rq.get('https://x')"),
    (
        "aliased order fn",
        "from order_executor import place_paper_order as _p; _p(1, 2, 3, 4)",
    ),
    ("call receiver", "import httpx; httpx.Client().get('https://x')"),
    ("attribute receiver", "self._session.get('https://x')"),
    ("raw socket", "import socket; socket.create_connection(('h', 80))"),
    ("subprocess", "import subprocess; subprocess.run(['curl', 'https://x'])"),
    ("bare imported get", "from requests import get; get('https://x')"),
    ("getattr dispatch", 'getattr(_m, "place_order")(1)'),
    ("dict dispatch", '_H = {"o": None}; _H["o"](1)'),
    ("list dispatch", "_L[0](1)"),
]
for label, snippet in CONTROLS:
    cviol, cunres = analyse(inject=snippet)
    caught = bool(cviol) or bool(sorted(set(cunres) - ALLOWED_LEAVES))
    print(f"  control {label:<22} {'CAUGHT' if caught else 'MISSED'}: {snippet}")
    if not caught:
        print(
            f"FAIL: positive control {label!r} did NOT trip -- this checker "
            f"cannot detect that form of call"
        )
        sys.exit(1)

if violations:
    for _v in violations:
        print(f"FAIL: shadow writer reaches a forbidden path: {_v}")
    sys.exit(1)
print("GATE_G5_PASS")
