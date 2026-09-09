"""Structural + consistency checks on PROMPT-where-is-the-edge.md.

Complements verify_prompt_numbers.py (which re-derives figures from source).
This one asserts the document is a *deep-research* brief rather than an
internal-analysis brief, that it carries no figure this session already
measured as stale, and that it is internally consistent.

Run with `--selftest` to exercise every assertion against a deliberately
broken fixture; that is the positive control for the absence checks, without
which "no stale number found" could simply mean the matcher never fires.

Emits VERIFY_STRUCTURE_PASS only when every assertion holds.
"""

from __future__ import annotations

import pathlib
import re
import sys

REQUIRED = [
    # (label, regex that must be PRESENT)
    ("web/research instruction", r"Use the web as well as the repo"),
    (
        "favorite-longshot framing",
        r"favorite[–-]longshot bias",
    ),
    (
        "well-calibrated-at-scale counterevidence",
        r"70,000[–-]73,000 resolved daily markets",
    ),
    (
        "the selection test is named as task 1",
        r"Your first task is to test exactly that",
    ),
    ("maker-\\$0 + rests thesis", r"pays \$0 maker fees and rests rather than crosses"),
    ("deliverable section", r"^## What to deliver"),
    ("stopping rule demanded", r"stopping rule"),
    ("re-derive instruction", r"Re-derive any number you intend to rely on"),
    ("read-only DB instruction", r"\?mode=ro"),
    ("paper_archive warning", r"paper_archive"),
    ("sealed pre-registration", r"registration is SEALED"),
    ("step 11 review", r"independent opus\s*\n?\s*review, is never skipped"),
    ("no bare pytest", r"Never run bare `pytest`"),
    ("disagreement section", r"^## How to disagree with this document"),
    ("anchor is env-overridable", r"`os\.getenv`-overridable"),
    (
        "gap is hardcoded",
        r"MAX_MODEL_MKT_GAP: float = 0\.25` is a \*\*hardcoded constant",
    ),
    ("lock n and pct stated together", r"143 evaluations with 3 locks \(2\.1%\)"),
    ("archived era marked closed", r"closed, will not move"),
    ("live era marked moving", r"moves — re-derive it"),
]

FORBIDDEN = [
    # (label, regex that must be ABSENT — each was measured stale on 2026-09-09)
    ("stale total P&L -484.36", r"484\.36"),
    ("stale core-prediction count 341", r"\b341 settled\b"),
    ("over-precise gap buckets", r"61\.3/54\.2/57\.9"),
    ("stale live-era figure presented as total", r"live era the remainder"),
]


def run(text: str) -> list[str]:
    problems: list[str] = []
    for label, pat in REQUIRED:
        if not re.search(pat, text, re.M):
            problems.append(f"MISSING: {label}")
    for label, pat in FORBIDDEN:
        if re.search(pat, text, re.M):
            problems.append(f"STALE/FORBIDDEN present: {label}")
    # internal consistency: a figure may not be called both fixed and moving
    if re.search(r"−?\$?432\.36[^\n]*moves", text):
        problems.append("INCONSISTENT: archived era described as moving")
    return problems


if "--selftest" in sys.argv:
    # positive control: a broken fixture must trip every class of assertion
    broken = "total was -484.36 over 341 settled predictions, buckets 61.3/54.2/57.9"
    got = run(broken)
    missing = [p for p in got if p.startswith("MISSING")]
    stale = [p for p in got if p.startswith("STALE")]
    if len(missing) < len(REQUIRED) or len(stale) < 3:
        print(
            f"SELFTEST FAILED: fixture tripped {len(missing)} missing / {len(stale)} stale"
        )
        raise SystemExit(1)
    print(
        f"selftest: broken fixture correctly tripped "
        f"{len(missing)} MISSING and {len(stale)} STALE assertions"
    )

args = [a for a in sys.argv[1:] if not a.startswith("--")]
if not args:
    print("FAIL: no prompt path given")
    raise SystemExit(1)
path = pathlib.Path(args[0])
problems = run(path.read_text(encoding="utf-8"))
print(f"assertions: {len(REQUIRED)} required + {len(FORBIDDEN)} forbidden")
for p in problems:
    print("  ", p)
if problems:
    print(f"{len(problems)} PROBLEM(S)")
    raise SystemExit(1)
print("VERIFY_STRUCTURE_PASS")
