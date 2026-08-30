"""G7: the scoped test set passes.

SCOPED, never the full suite. The set is derived rather than hand-listed: the
new module, plus every existing module that imports or exercises the two files
this change touches. A hand-picked list is how a "scoped" run silently stops
covering the callers it broke.
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
NEW = "tests/test_price_recal_shadow_log.py"
# The symbols this change actually added or altered. A test module is in scope
# if it names one of them, not merely if it imports cron or tracker (hundreds
# do, and that is the full suite by another name).
TOUCHED = (
    "price_recal",
    "_MIGRATIONS",
    "_SCHEMA_VERSION",
    "_run_migrations",
    "exit_rule_shadow_log",  # the sibling writer, same cron block
    "batch_log_analysis_attempts",  # the call site immediately above the wiring
)

modules = {NEW}
for path in sorted((ROOT / "tests").glob("test_*.py")):
    text = path.read_text(encoding="utf-8", errors="replace")
    if any(t in text for t in TOUCHED):
        modules.add(f"tests/{path.name}")

targets = sorted(modules)
print(f"scoped set ({len(targets)} module(s)), derived from: {TOUCHED}")
for t in targets:
    print(f"  {t}")

total = len(list((ROOT / "tests").glob("test_*.py")))
print(f"(the full suite is {total} modules; this run is {len(targets)})")
if len(targets) > total * 0.5:
    print("FAIL: the 'scoped' set is more than half the suite -- that is the "
          "full suite by another name; narrow TOUCHED")
    sys.exit(1)

r = subprocess.run(
    [sys.executable, "-m", "pytest", *targets, "-q", "--no-header"],
    cwd=ROOT,
    text=True,
    encoding="utf-8",
    errors="replace",
)
if r.returncode != 0:
    print("FAIL: scoped tests failed")
    sys.exit(1)
print("GATE_G7_PASS")
