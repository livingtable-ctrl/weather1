"""G4: the new migrations are APPENDED, not inserted, and the version matches.

_MIGRATIONS is append-only because _run_migrations uses the list INDEX as the
version cursor: a statement inserted mid-list is skipped forever on every DB
that has already passed that index. This checks the property against master
rather than trusting the comment.
"""

from __future__ import annotations

import ast
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import tracker  # noqa: E402

failures: list[str] = []


def need(cond: bool, msg: str) -> None:
    if not cond:
        failures.append(msg)


mig = tracker._MIGRATIONS
print(f"migrations: {len(mig)}   _SCHEMA_VERSION: {tracker._SCHEMA_VERSION}")
need(
    tracker._SCHEMA_VERSION == len(mig),
    f"_SCHEMA_VERSION ({tracker._SCHEMA_VERSION}) != len(_MIGRATIONS) ({len(mig)})",
)

# The list as it stands on master must be a strict PREFIX of the list now.
base = subprocess.run(
    ["git", "merge-base", "HEAD", "master"],
    cwd=ROOT,
    capture_output=True,
    text=True,
).stdout.strip()
old_src = subprocess.run(
    ["git", "show", f"{base}:tracker.py"],
    cwd=ROOT,
    capture_output=True,
    encoding="utf-8",
    errors="replace",
).stdout


# Compare the list ELEMENTS as source text, not as evaluated values: the list
# contains at least one call (sql_normalize_iso_column) that cannot be exec'd
# in isolation, and the property under test is textual identity of the prefix
# anyway.
def elements(src: str) -> list[str]:
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and any(
                isinstance(t, ast.Name) and t.id == "_MIGRATIONS" for t in node.targets
            )
            and isinstance(node.value, ast.List)
        ):
            return [ast.dump(e) for e in node.value.elts]
    raise SystemExit("could not locate the _MIGRATIONS list literal")


old = elements(old_src)
new_els = elements((ROOT / "tracker.py").read_text(encoding="utf-8"))
print(f"migrations on master: {len(old)}")

need(len(new_els) >= len(old), "migrations were REMOVED, not appended")
mismatch = next(
    (i for i in range(min(len(old), len(new_els))) if old[i] != new_els[i]),
    None,
)
need(
    mismatch is None,
    f"_MIGRATIONS index {mismatch} differs from master -- a statement was "
    f"inserted or edited mid-list, so every DB already past that index will "
    f"skip it forever",
)

added = mig[len(old) :]
print(f"appended: {len(added)} statement(s)")
need(len(added) == 2, f"expected 2 appended statements, found {len(added)}")
need(
    any("CREATE TABLE IF NOT EXISTS price_recal_shadow_log" in s for s in added),
    "the picks table is not among the appended statements",
)
need(
    any("CREATE UNIQUE INDEX" in s and "price_recal_shadow_log" in s for s in added),
    "the dedup index is not among the appended statements",
)
need(
    tracker._SCHEMA_VERSION == len(old) + len(added),
    "_SCHEMA_VERSION was not advanced by the number of appended statements",
)

if failures:
    for f in failures:
        print(f"FAIL: {f}")
    sys.exit(1)
print("GATE_G4_PASS")
