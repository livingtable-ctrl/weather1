"""Measure what fraction of the handoff's numeric claims any gate actually covers.

Coverage is defined by MUTATION, not by inspection: perturb one number in the
document, run the oracle, and see whether anything fails. If nothing fails,
that claim is ungated — the ledger would certify the document with that figure
set to a wrong value.

This exists because the gated set was chosen by the same person who wrote the
document, which is the selection problem the document itself is about.

READ-ONLY with respect to the repo: the doc is restored from an in-memory
snapshot after every mutation and verified byte-identical at the end.

Usage: python .unlazy/coverage_handoff.py [--limit N] [--verbose]
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

# Numbers that are prose, not claims: years, section refs, list markers.
SKIP_CONTEXT = re.compile(
    r"backlog\.txt|~L\d|20\d\d-\d\d-\d\d|\bL\d{3,}|version|Co-Authored", re.I
)


def perturb(tok: str) -> str:
    """Change a number to a clearly different value of the same shape."""
    if "." in tok:
        head, tail = tok.split(".", 1)
        bumped = str((int(tail[0]) + 5) % 10) + tail[1:]
        return f"{head}.{bumped}"
    return str(int(tok) + 7)


def _write(path: pathlib.Path, data: str, attempts: int = 5) -> None:
    """Write with retry. A transient Windows lock (antivirus, a formatter, an
    editor) once aborted this script INSIDE its restore step, which is the one
    place a crash could leave the document mutated on disk."""
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
    """True if the oracle passes (exit 0)."""
    r = subprocess.run(
        [sys.executable, str(ORACLE), "--all"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    return r.returncode == 0


def main() -> int:
    verbose = "--verbose" in sys.argv
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])

    snapshot = DOC.read_text(encoding="utf-8")
    if not run_oracle():
        print("BASELINE FAILING — fix the oracle before measuring coverage")
        return 2

    lines = snapshot.split("\n")
    targets: list[tuple[int, str, str]] = []
    for i, line in enumerate(lines):
        if SKIP_CONTEXT.search(line):
            continue
        for m in re.finditer(r"(?<![\w.-])(\d+\.\d+|\d{2,4})(?![\w.-])", line):
            tok = m.group(1)
            if tok in {"2026", "2025", "2027", "0", "1"}:
                continue
            targets.append((i, tok, line.strip()[:70]))
    if limit:
        targets = targets[:limit]

    covered: list[tuple[int, str, str]] = []
    uncovered: list[tuple[int, str, str]] = []
    try:
        for idx, (li, tok, ctx) in enumerate(targets, 1):
            mutated = list(lines)
            mutated[li] = mutated[li].replace(tok, perturb(tok), 1)
            DOC.write_text("\n".join(mutated), encoding="utf-8")
            passed = run_oracle()
            _write(DOC, snapshot)
            (uncovered if passed else covered).append((li + 1, tok, ctx))
            if verbose:
                print(
                    f"  [{idx}/{len(targets)}] L{li + 1} {tok:>8} "
                    f"{'UNGATED' if passed else 'gated  '}  {ctx}"
                )
    finally:
        _write(DOC, snapshot)
        assert DOC.read_text(encoding="utf-8") == snapshot, "RESTORE FAILED"

    # ---- classify the ungated set -----------------------------------------
    # Three buckets. Only the first rule involves judgement, and it is narrow:
    #   PROSE     the token is the 0.5 null reference itself, or a table header
    #             cell -- it asserts nothing about this corpus.
    #   RESTATED  the identical value is gated somewhere else, so a wrong edit
    #             here is caught by --restatements only if that specific phrase
    #             is covered; otherwise the doc can contradict itself silently.
    #   GENUINE   a factual claim about this corpus that NO gate reacts to.
    gated_values = {tok for _ln, tok, _ctx in covered}
    prose, restated, genuine = [], [], []
    for ln, tok, ctx in uncovered:
        if tok in {"0.5", "0.50"} and (
            "z vs" in ctx
            or "fixing 0.5" in ctx
            or "ranks a random" in ctx
            or "no signal" in ctx
            or "0.50 is" in ctx
        ):
            prose.append((ln, tok, ctx))
        elif tok in gated_values:
            restated.append((ln, tok, ctx))
        else:
            genuine.append((ln, tok, ctx))

    print()
    print("UNGATED, CLASSIFIED")
    tot_u = len(uncovered)
    for label, bucket in (
        ("PROSE (null refs / headers)", prose),
        ("RESTATED (value gated elsewhere)", restated),
        ("GENUINE ungated claims", genuine),
    ):
        print(
            f"  {label:<34} {len(bucket):>4}  ({100 * len(bucket) / tot_u:.1f}% of ungated)"
        )
    print()
    print("GENUINE UNGATED CLAIMS — no gate reacts to these:")
    for ln, tok, ctx in genuine[:60]:
        print(f"   L{ln:<4} {tok:>8}   {ctx}")
    if len(genuine) > 60:
        print(f"   ... and {len(genuine) - 60} more")

    total = len(covered) + len(uncovered)
    pct = 100 * len(covered) / total if total else 0.0
    print()
    print(f"NUMERIC CLAIMS TESTED : {total}")
    print(f"  gated (a mutation is caught) : {len(covered)}  ({pct:.1f}%)")
    print(f"  UNGATED                      : {len(uncovered)}  ({100 - pct:.1f}%)")
    print()
    print("UNGATED CLAIMS — the ledger would certify the document with these wrong:")
    for ln, tok, ctx in uncovered[:40]:
        print(f"   L{ln:<4} {tok:>8}   {ctx}")
    if len(uncovered) > 40:
        print(f"   ... and {len(uncovered) - 40} more")
    print()
    print("doc restored byte-identical")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
