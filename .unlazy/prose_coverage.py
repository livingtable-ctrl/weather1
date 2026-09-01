"""Measure which PROSE claims in the handoff have no assertion gate.

Numeric coverage is measured by mutation. Prose cannot be: perturbing a
sentence with no number in it changes nothing an oracle reads. So this
measures differently — it extracts sentences that make a falsifiable factual
assertion, then reports which ones no `--assertions` entry corresponds to.

WHY THIS EXISTS: the assertion list in audit_handoff_ext.py was written by the
same person who wrote the document, choosing which of their own claims to
test. That is the selection problem the document itself is about, one level
up. This tool does not fix it — nothing can fully — but it makes the omission
countable instead of invisible.

The extraction is deliberately GENEROUS: it over-collects rather than
under-collects, because a claim wrongly listed as ungated costs a moment's
review, while one wrongly omitted is exactly the failure being measured.

READ-ONLY.

Usage: python .unlazy/prose_coverage.py [--list]
"""

from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "HANDOFF-confidence-collapse-2026-08-30.md"
# EVERY module that registers assertion gates must be listed. Omitting one
# makes this tool under-report coverage and silently credit no improvement --
# which happened on 2026-08-30 when audit_handoff_prose.py was added with 15
# new gates and this tool still reported the old 4.3%.
GATE_MODULES = [
    ROOT / ".unlazy" / "audit_handoff_ext.py",
    ROOT / ".unlazy" / "audit_handoff_prose.py",
    ROOT / ".unlazy" / "audit_handoff_prose2.py",
]

# A sentence asserts something checkable if it makes a claim about the corpus,
# the code, or a causal relation. These are the markers.
ASSERTIVE = re.compile(
    r"\b(cannot|can not|never|always|does not|did not|is not|was not|no longer|"
    r"proves?|confirms?|refut\w+|establish\w*|rules? out|eliminat\w+|"
    r"explains?|caused?|because|therefore|so that|means that|"
    r"survives?|holds?|fails?|invariant|unchanged|halved|collapsed?)\b",
    re.I,
)

# Sentences that are instructions, meta-commentary or hedges assert nothing
# testable about the data.
NON_CLAIM = re.compile(
    r"\b(do not present|must stratify|should start|read this|check this|"
    r"look for|find when|resolve this|verify|before acting|next session|"
    r"how to re-derive|usage|treat this|worth|would be|may be|might)\b",
    re.I,
)


def sentences(text: str) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for i, line in enumerate(text.split("\n"), 1):
        s = line.strip()
        if not s or s.startswith(("|", "#", "```", "    ")):
            continue
        for part in re.split(r"(?<=[.!?])\s+", s):
            p = part.strip()
            if len(p) > 40:
                out.append((i, p))
    return out


def main() -> int:
    text = DOC.read_text(encoding="utf-8")
    ext = chr(10).join(
        m.read_text(encoding="utf-8") for m in GATE_MODULES if m.exists()
    )

    # Which claims are gated: pull the regexes out of EVERY claims table.
    # Collecting only the first one under-reported coverage and credited no
    # improvement when a second gate module was added on 2026-08-30.
    blocks = []
    for marker in ("CLAIMS = [", "PROSE_CLAIMS = [", "PROSE_CLAIMS_2 = ["):
        i = 0
        while True:
            i = ext.find(marker, i)
            if i < 0:
                break
            end = ext.find(chr(10) + "]", i)
            blocks.append(ext[i:end] if end > 0 else ext[i:])
            i += len(marker)
    block = chr(10).join(blocks)
    # NOTE: match any r"..." in the block. An earlier version required the
    # literal `(r"` sequence, which stopped matching the moment ruff format
    # split the tuples across lines -- so the tool silently reported 0%
    # coverage and would have been believed. A measurement tool can be
    # vacuous exactly like a gate can.
    gated_patterns = re.findall(r'r"((?:[^"\\]|\\.)+)"', block)
    if not gated_patterns:
        raise SystemExit(
            "prose_coverage: extracted ZERO gate patterns -- the extractor is "
            "broken, not the document. Refusing to report a coverage number."
        )

    claims = [
        (ln, s)
        for ln, s in sentences(text)
        if ASSERTIVE.search(s) and not NON_CLAIM.search(s)
    ]

    # Gate patterns are matched against the WHOLE document, then mapped back to
    # line numbers. Matching them against one extracted sentence at a time
    # under-reported coverage: several gate regexes deliberately span a line
    # break (the document hard-wraps), so they could never match a single
    # line and their claims were counted as ungated.
    gated_lines: set[int] = set()
    for pat in gated_patterns:
        try:
            rx = re.compile(pat, re.S)
        except re.error:
            continue
        for m in rx.finditer(text):
            first = text.count(chr(10), 0, m.start()) + 1
            last = text.count(chr(10), 0, m.end()) + 1
            for ln in range(first, last + 1):
                gated_lines.add(ln)

    gated: list[tuple[int, str]] = []
    ungated: list[tuple[int, str]] = []
    for ln, s in claims:
        (gated if ln in gated_lines else ungated).append((ln, s))

    # Split the ungated set. A META sentence talks about this document's own
    # revision history ("an earlier draft said X"). It is checkable only
    # against the document, never against evidence, so gating it would test
    # nothing. EVIDENTIAL sentences make a claim about the corpus, the code or
    # the world, and are the ones a truth condition can be written for.
    META = re.compile(
        r"earlier draft|earlier version|this file|this document|"
        r"CORRECTION|RETRACT|is kept only because|reasoning is recorded|"
        r"read the correction|instructive|not independently confirmed|"
        r"an earlier pass|prior handoffs|was briefly asserted|"
        r"surfaced by gating|found by gating|the gate for this claim",
        re.I,
    )
    meta = [(ln, s) for ln, s in ungated if META.search(s)]
    evidential = [(ln, s) for ln, s in ungated if not META.search(s)]

    total = len(claims)
    print(f"PROSE CLAIMS DETECTED       : {total}")
    print(f"  UNGATED split -> META {len(meta)} | EVIDENTIAL {len(evidential)}")
    print(
        f"  matched by an assertion gate : {len(gated)}  "
        f"({100 * len(gated) / total:.1f}%)"
        if total
        else "  none"
    )
    print(
        f"  UNGATED                      : {len(ungated)}  "
        f"({100 * len(ungated) / total:.1f}%)"
        if total
        else ""
    )
    print()
    print("NOTE the extraction over-collects by design; a share of the ungated")
    print("list will be commentary rather than claims. The number is an upper")
    print("bound on unguarded prose, not a defect count.")
    if "--list" in sys.argv:
        print()
        print("UNGATED *EVIDENTIAL* CLAIMS (meta-commentary excluded):")
        for ln, s in evidential[:60]:
            print(f"   L{ln:<4} {s[:104]}")
        if len(evidential) > 60:
            print(f"   ... and {len(evidential) - 60} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
