"""Which figures are BOTH singletons and ungated?

A figure stated once cannot be cross-checked against a restatement of itself,
so it is guarded only if a gate derives it. This intersects the two analyses
that were previously run separately -- singleton-ness and mutation coverage --
because neither alone identifies the genuinely unguarded set.

Reuses coverage_handoff's mutation definition of "gated": perturb the figure,
run the oracle, see whether anything fails.

READ-ONLY. The document is restored from an in-memory snapshot.

Usage: python .unlazy/singleton_report.py [--list]
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys
import time
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "HANDOFF-confidence-collapse-2026-08-30.md"
ORACLE = ROOT / ".unlazy" / "audit_handoff.py"

FIG = re.compile(r"(?<![\w.-])(\d+\.\d{3,4})(?![\w.-])")


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


def run_oracle() -> bool:
    r = subprocess.run(
        [sys.executable, str(ORACLE), "--all"], cwd=ROOT, capture_output=True, text=True
    )
    return r.returncode == 0


def perturb(tok: str) -> str:
    head, tail = tok.split(".", 1)
    return f"{head}.{str((int(tail[0]) + 5) % 10)}{tail[1:]}"


def main() -> int:
    snapshot = DOC.read_text(encoding="utf-8")
    if not run_oracle():
        print("BASELINE FAILING -- fix the oracle first")
        return 2

    counts = Counter(FIG.findall(snapshot))
    singles = {k for k, v in counts.items() if v == 1}

    lines = snapshot.split("\n")
    targets: list[tuple[int, str, str]] = []
    for i, line in enumerate(lines):
        for m in FIG.finditer(line):
            if m.group(1) in singles:
                targets.append((i, m.group(1), line.strip()[:78]))

    gated: list[tuple[int, str, str]] = []
    ungated: list[tuple[int, str, str]] = []
    try:
        for li, tok, ctx in targets:
            mutated = list(lines)
            mutated[li] = mutated[li].replace(tok, perturb(tok), 1)
            _write(DOC, "\n".join(mutated))
            passed = run_oracle()
            _write(DOC, snapshot)
            (ungated if passed else gated).append((li + 1, tok, ctx))
    finally:
        _write(DOC, snapshot)
        assert DOC.read_text(encoding="utf-8") == snapshot, "RESTORE FAILED"

    tot = len(targets)
    print(f"SINGLETON 4dp FIGURES : {tot}")
    print(f"  gated   : {len(gated)}")
    print(f"  UNGATED : {len(ungated)}   <- the genuinely unguarded set")
    if "--list" in sys.argv:
        print()
        for ln, tok, ctx in ungated:
            print(f"   L{ln:<4} {tok:>9}   {ctx}")
    print()
    print("doc restored byte-identical")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
