"""Positive controls for .unlazy/audit_handoff.py.

An absence-check that has never been shown to fire is not evidence. This
mutates the handoff in memory, restores from an in-memory snapshot (never
`git checkout --`, which would also discard unrelated work), and asserts the
oracle CATCHES each mutation.

A mutation that survives means that gate is vacuous.
"""

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve()
REPO = pathlib.Path(
    r"C:\Users\thesa\claude kalshi\.claude\worktrees\price-recalibration-validation-720043"
)
DOC = REPO / "docs" / "HANDOFF-confidence-collapse-2026-08-30.md"
ORACLE = REPO / ".unlazy" / "audit_handoff.py"

MUTANTS = [
    # (label, check-flag, find, replace)
    # Retargeted 2026-08-30 for the 212-line condensed document. Three earlier
    # mutants anchored on sections that the condensation deleted; the harness
    # reported ANCHOR NOT FOUND rather than passing, which is the behaviour it
    # exists for.
    (
        "number: AUC MayJun model",
        "--numbers",
        "| May-Jun | **model** | 198 | **0.6828** |",
        "| May-Jun | **model** | 198 | **0.7828** |",
    ),
    ("number: monthly Aug AUC", "--numbers", "Aug 0.5085 (74)", "Aug 0.6085 (74)"),
    (
        "number: forecast error Jul",
        "--tables",
        "| 2026-07 | 56 | **1.18** | 2.01 | 4.14 |",
        "| 2026-07 | 56 | **1.18** | 2.51 | 4.14 |",
    ),
    (
        "number: traded-subset AUC",
        "--numbers",
        "| **63** | **0.4849** |",
        "| **63** | **0.6849** |",
    ),
    (
        "number: stratified above JulAug",
        "--strata",
        "| above | Jul-Aug | model | 85 | 0.5786 |",
        "| above | Jul-Aug | model | 85 | 0.6786 |",
    ),
    (
        "number: composition between",
        "--strata",
        "| `between` | **55.6%** | **2.8%** |",
        "| `between` | **65.6%** | **2.8%** |",
    ),
    (
        "number: bootstrap CI",
        "--bootstrap",
        "95% CI        = [-0.0794, +0.3446]",
        "95% CI        = [-0.0794, +0.4446]",
    ),
    ("citation: bogus line", "--citations", "`cron.py:2202`", "`cron.py:999999`"),
    ("citation: bogus file", "--citations", "tracker.py:1630", "nosuchmod.py:1630"),
    (
        "stale: withdrawn conclusion",
        "--contradictions",
        "## Bottom line",
        "## Bottom line" + chr(10) + chr(10) + "The model specifically broke.",
    ),
    (
        "assertion: delete an anchor",
        "--assertions",
        "invariant under temperature scaling",
        "invariant under [REMOVED]",
    ),
]


def run(flag):
    r = subprocess.run(
        [sys.executable, str(ORACLE), flag], cwd=REPO, capture_output=True, text=True
    )
    return r.returncode, r.stdout


snapshot = DOC.read_text(encoding="utf-8")
print(f"baseline doc: {len(snapshot)} bytes")
code, out = run("--all")
print(f"baseline oracle exit={code} (expect 0)")
if code != 0:
    print("BASELINE ALREADY FAILING — fix before mutation testing")
    print(out)
    raise SystemExit(2)

survivors = []
try:
    for label, flag, find, repl in MUTANTS:
        if find not in snapshot:
            survivors.append(
                f"{label}: ANCHOR NOT FOUND ({find[:40]!r}) — mutation never applied"
            )
            continue
        DOC.write_text(snapshot.replace(find, repl, 1), encoding="utf-8")
        code, out = run(flag)
        DOC.write_text(snapshot, encoding="utf-8")  # restore immediately
        if code == 0:
            survivors.append(f"{label}: SURVIVED — {flag} passed on a mutated doc")
            print(f"  {label:34s} SURVIVED  <-- gate is vacuous here")
        else:
            print(f"  {label:34s} killed")
finally:
    DOC.write_text(snapshot, encoding="utf-8")
    assert DOC.read_text(encoding="utf-8") == snapshot, "RESTORE FAILED"
    print("doc restored byte-identical")

print()
if survivors:
    print(f"{len(survivors)} SURVIVOR(S):")
    for s in survivors:
        print("   -", s)
    raise SystemExit(1)
print("ALL MUTANTS KILLED — the oracle can fail honestly")
