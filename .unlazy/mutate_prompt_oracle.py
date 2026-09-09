"""Prove verify_prompt_numbers.py is not vacuous.

Applies independent mutations to a COPY of the prompt (never the original),
runs the numbers oracle against each one alone, and requires every single
mutation to be caught. A mutation that survives means the oracle does not
actually bind that figure.

Emits MUTATION_ORACLE_PASS only when every mutation is detected.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(r"C:\Users\thesa\claude kalshi")
ORACLE = ROOT / ".unlazy" / "verify_prompt_numbers.py"

MUTATIONS = [
    ("above+lock P&L", "**+282.81**", "**+282.99**"),
    ("above+lock n", "| 17 |", "| 18 |"),
    (
        "lock count+pct",
        "143 evaluations with 3 locks (2.1%)",
        "143 evaluations with 4 locks (2.8%)",
    ),
    ("prereg counts", "**14 picks logged, 10 settled", "**15 picks logged, 11 settled"),
    ("ensemble Brier", "Brier 0.2570 lifetime", "Brier 0.2599 lifetime"),
    ("between+lock P&L", "**−184.45**", "**−184.99**"),
    ("guard commit", "commit `e395392b`", "commit `deadbee`"),
]

if len(sys.argv) < 2:
    print("FAIL: pass the prompt path as argv[1]")
    raise SystemExit(1)
src = pathlib.Path(sys.argv[1])
base = src.read_text(encoding="utf-8")

# Control: the unmutated document must PASS, or "everything fails" would look like success.
with tempfile.TemporaryDirectory() as td:
    ctl = pathlib.Path(td) / "control.md"
    ctl.write_text(base, encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(ORACLE), str(ctl)],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    if r.returncode != 0:
        print(
            "FAIL: control (unmutated) did not pass the oracle — cannot attribute "
            "mutation failures to the mutations"
        )
        print(r.stdout[-800:])
        raise SystemExit(1)
print("control: unmutated prompt passes the oracle")

survivors: list[str] = []
for label, old, new in MUTATIONS:
    if base.count(old) < 1:
        survivors.append(
            f"{label}: anchor text not present — mutation could not be applied"
        )
        continue
    with tempfile.TemporaryDirectory() as td:
        m = pathlib.Path(td) / "mutant.md"
        m.write_text(base.replace(old, new, 1), encoding="utf-8")
        r = subprocess.run(
            [sys.executable, str(ORACLE), str(m)],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
        )
    if r.returncode == 0:
        survivors.append(f"{label}: SURVIVED — oracle does not bind this figure")
    else:
        print(f"  killed: {label}")

print(f"mutations: {len(MUTATIONS)}, survivors: {len(survivors)}")
for s in survivors:
    print("  ", s)
if survivors:
    raise SystemExit(1)
print("MUTATION_ORACLE_PASS")
