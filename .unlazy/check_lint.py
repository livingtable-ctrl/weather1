"""G9: the repo's own pre-commit hooks pass on the changed files.

Runs pre-commit as the repo configures it (ruff, ruff-format, mypy with the
repo's own flags) rather than a bare local mypy, whose settings differ from the
hook's and which therefore proves nothing about what a commit will do.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
FILES = [
    "cron.py",
    "tracker.py",
    "tests/test_price_recal_shadow_log.py",
]


def run(cmd: list[str]):
    return subprocess.run(
        cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        errors="replace"
    )


PRECOMMIT = [sys.executable, "-m", "pre_commit"]
probe = run([*PRECOMMIT, "--version"])
if probe.returncode != 0:
    print("FAIL: pre-commit is not available; the repo's own hook is the only "
          "lint configuration that binds a commit, and a bare local ruff/mypy "
          "is not a substitute")
    print(probe.stderr.strip()[:400])
    sys.exit(1)
print(f"pre-commit: {probe.stdout.strip()}")

# NOT read-only otherwise: `pre-commit run` includes ruff-format and
# `ruff --fix`, both of which REWRITE files in place. In a worktree carrying
# uncommitted work, a lint gate that edits the code it is checking is a
# verification that changes its own subject. Snapshot first, restore after, and
# fail loudly if anything moved rather than silently keeping the rewrite.
before = {f: (ROOT / f).read_bytes() for f in FILES}
r = run([*PRECOMMIT, "run", "--files", *FILES])
rewritten = [f for f in FILES if (ROOT / f).read_bytes() != before[f]]
for f in rewritten:
    (ROOT / f).write_bytes(before[f])
if rewritten:
    print(f"FAIL: the hooks rewrote {rewritten} -- restored from the pre-run "
          f"snapshot. Apply the formatting deliberately and re-run; this gate "
          f"must not be the thing that edits the code it certifies.")
    print(r.stdout[-2000:])
    sys.exit(1)
print(r.stdout[-4000:])
if r.stderr.strip():
    print("stderr:", r.stderr[-1500:])
if r.returncode != 0:
    print("FAIL: pre-commit reported failures on the changed files")
    sys.exit(1)
print("GATE_G9_PASS")
