"""Positive controls for the prose gates.

A prose gate has two halves: the document must still make the claim, and the
evidence must support it. The evidence half cannot be mutation-tested here --
the database is read-only and must stay that way. The DOCUMENT half can, and
must be, because a gate whose regex silently stops matching would report OK
while guarding nothing. That failure mode has already occurred twice in this
project's tooling.

Each mutant deletes or corrupts the sentence a gate anchors to and asserts the
gate FAILS. The document is restored from an in-memory snapshot after every
mutation and verified byte-identical at the end.

Usage: python .unlazy/mutate_prose_gates.py
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "HANDOFF-confidence-collapse-2026-08-30.md"
ORACLE = ROOT / ".unlazy" / "audit_handoff.py"
MODULES = [
    ROOT / ".unlazy" / "audit_handoff_prose.py",
    ROOT / ".unlazy" / "audit_handoff_prose2.py",
]
FLAGS = {"audit_handoff_prose.py": "--prose", "audit_handoff_prose2.py": "--prose2"}


def _write(path: pathlib.Path, data: str, attempts: int = 5) -> None:
    last: Exception | None = None
    for _ in range(attempts):
        try:
            path.write_text(data, encoding="utf-8")
            return
        except OSError as exc:  # noqa: PERF203
            last = exc
            time.sleep(0.25)
    raise RuntimeError(f"could not write {path}: {last}")


def run(flag: str) -> bool:
    r = subprocess.run(
        [sys.executable, str(ORACLE), flag], cwd=ROOT, capture_output=True, text=True
    )
    return r.returncode == 0


def main() -> int:
    snapshot = DOC.read_text(encoding="utf-8")
    if not (run("--prose") and run("--prose2")):
        print("BASELINE FAILING -- fix the gates before mutation testing")
        return 2

    # Pull each gate's anchor regex and the flag that runs it.
    anchors: list[tuple[str, str]] = []
    for mod in MODULES:
        src = mod.read_text(encoding="utf-8")
        flag = FLAGS[mod.name]
        for marker in ("PROSE_CLAIMS = [", "PROSE_CLAIMS_2 = ["):
            i = src.find(marker)
            if i < 0:
                continue
            block = src[i : src.find(chr(10) + "]", i)]
            for pat in re.findall(r'r"((?:[^"\\]|\\.)+)"', block):
                anchors.append((flag, pat))
    if not anchors:
        print("no anchors extracted -- the harness is broken, not the gates")
        return 2

    survivors: list[str] = []
    try:
        for flag, pat in anchors:
            try:
                rx = re.compile(pat, re.S)
            except re.error:
                survivors.append(f"{pat[:50]}: pattern does not compile")
                continue
            if not rx.search(snapshot):
                survivors.append(f"{pat[:50]}: ANCHOR ABSENT from the document")
                continue
            # Delete EVERY matched span. Removing only the first occurrence
            # left a duplicate phrase behind and the gate still matched --
            # which reads as a survivor but is a harness defect, not a vacuous
            # gate. Distinguishing the two matters.
            mutated = rx.sub("[REMOVED]", snapshot)
            _write(DOC, mutated)
            passed = run(flag)
            _write(DOC, snapshot)
            if passed:
                survivors.append(f"{pat[:60]}: SURVIVED -- {flag} passed without it")
                print(f"  {pat[:58]:60s} SURVIVED")
            else:
                print(f"  {pat[:58]:60s} killed")
    finally:
        _write(DOC, snapshot)
        assert DOC.read_text(encoding="utf-8") == snapshot, "RESTORE FAILED"
        print("doc restored byte-identical")

    print()
    print(f"anchors tested: {len(anchors)}")
    if survivors:
        print(f"{len(survivors)} SURVIVOR(S):")
        for s in survivors:
            print("   -", s)
        return 1
    print("ALL PROSE ANCHORS KILLED -- every gate notices its claim disappearing")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
