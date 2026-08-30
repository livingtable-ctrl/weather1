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


# DERIVED from the diff, not hand-listed. The hand-list omitted
# tests/test_sameday_only.py, which this change also modifies, so G9's claim to
# lint "the changed files" was false as measured -- and a hand-list drifts again
# every time the change grows.
def _changed_python_files() -> list[str]:
    base = subprocess.run(
        ["git", "merge-base", "HEAD", "master"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()
    out = subprocess.run(
        ["git", "diff", "--name-only", "-z", f"{base}..HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    tracked = [f for f in out.split(chr(0)) if f.endswith(".py")]
    dirty = subprocess.run(
        ["git", "diff", "--name-only", "-z", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    tracked += [f for f in dirty.split(chr(0)) if f.endswith(".py")]
    # Untracked new .py files are invisible to `git diff` entirely.
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    tracked += [f for f in untracked.split(chr(0)) if f.endswith(".py")]
    # .exists() drops deleted files, which pre-commit cannot lint.
    return sorted({f for f in tracked if (ROOT / f).exists()})


FILES = _changed_python_files()
# AN EMPTY LIST IS A FAILURE, NOT A PASS. `pre-commit run --files` with no
# files skips every hook and exits 0, so without this the gate prints
# GATE_G9_PASS having linted nothing -- and the list goes empty in the ordinary
# case: once this branch merges, merge-base(HEAD, master) == HEAD and the diff
# is empty. A gate that certifies most loudly when it has least to say is worse
# than no gate.
if not FILES:
    print(
        "FAIL: no changed Python files resolved. Either nothing changed (in "
        "which case this gate has nothing to certify and must not claim to) "
        "or the derivation is broken."
    )
    sys.exit(1)


def run(cmd: list[str]):
    return subprocess.run(
        cmd,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


PRECOMMIT = [sys.executable, "-m", "pre_commit"]
probe = run([*PRECOMMIT, "--version"])
if probe.returncode != 0:
    print(
        "FAIL: pre-commit is not available; the repo's own hook is the only "
        "lint configuration that binds a commit, and a bare local ruff/mypy "
        "is not a substitute"
    )
    print(probe.stderr.strip()[:400])
    sys.exit(1)
print(f"pre-commit: {probe.stdout.strip()}")
print(f"linting {len(FILES)} changed file(s): {FILES}")

# NOT read-only otherwise: `pre-commit run` includes ruff-format and
# `ruff --fix`, both of which REWRITE files in place. In a worktree carrying
# uncommitted work, a lint gate that edits the code it is checking is a
# verification that changes its own subject. Snapshot first, restore after, and
# fail loudly if anything moved rather than silently keeping the rewrite.
before = {f: (ROOT / f).read_bytes() for f in FILES}
try:
    r = run([*PRECOMMIT, "run", "--files", *FILES])
finally:
    # try/finally, so an interrupt during the subprocess cannot leave the
    # hooks' rewrite on disk. Nothing is lost either way (the pre-run bytes are
    # in git), but a gate whose whole justification is "must not be the thing
    # that edits the code it certifies" should not depend on completing.
    rewritten = [f for f in FILES if (ROOT / f).read_bytes() != before[f]]
    for f in rewritten:
        (ROOT / f).write_bytes(before[f])
if rewritten:
    print(
        f"FAIL: the hooks rewrote {rewritten} -- restored from the pre-run "
        f"snapshot. Apply the formatting deliberately and re-run; this gate "
        f"must not be the thing that edits the code it certifies."
    )
    print(r.stdout[-2000:])
    sys.exit(1)
print(r.stdout[-4000:])
if r.stderr.strip():
    print("stderr:", r.stderr[-1500:])
if r.returncode != 0:
    print("FAIL: pre-commit reported failures on the changed files")
    sys.exit(1)
print("GATE_G9_PASS")
