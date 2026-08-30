"""Run a -k selection of the scoped module and emit a success-only token.

Used by the gates whose outcome is "these specific behaviours hold". A bare
pytest run prints no token this ledger could match, and matching on "passed"
would also match "0 passed" -- so the selection's test count is asserted too.
A -k expression that silently stops matching is the failure mode this guards.
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCOPED = "tests/test_price_recal_shadow_log.py"

if len(sys.argv) < 4:
    raise SystemExit("usage: run_selected.py <-k expr> <min tests> <TOKEN>")
expr, minimum, token = sys.argv[1], int(sys.argv[2]), sys.argv[3]

r = subprocess.run(
    [sys.executable, "-m", "pytest", SCOPED, "-q", "--no-header", "-k", expr],
    cwd=ROOT,
    capture_output=True,
    text=True,
    encoding="utf-8",
    errors="replace",
)
print(r.stdout[-2500:])
if r.returncode != 0:
    print(f"FAIL: selection {expr!r} did not pass")
    sys.exit(1)

m = re.search(r"(\d+) passed", r.stdout)
count = int(m.group(1)) if m else 0
print(f"selected {count} test(s) for {expr!r} (minimum {minimum})")
if count < minimum:
    print(
        f"FAIL: only {count} test(s) matched {expr!r}; the selection has "
        f"drifted and this gate is passing on less than it claims"
    )
    sys.exit(1)
print(token)
