"""G1: the protocol commit must land strictly before any implementation commit.

Proves the pre-commitment from git history rather than from an assertion in the
text. Walks the first-parent history of HEAD, finds the commit that introduced
the pre-registration entry into backlog.txt, and finds the earliest commit that
touched tracker.py or cron.py at or after the fork point from master. The former
must be an ancestor of the latter.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
MARKER = "FORWARD-VALIDATION PROTOCOL FOR THE PRICE-RECALIBRATION RULE"
IMPL = ("tracker.py", "cron.py")


def git(*args: str) -> str:
    r = subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8"
    )
    if r.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed:\n{r.stderr}")
    return r.stdout.strip()


def fail(msg: str) -> None:
    print(f"FAIL: {msg}")
    sys.exit(1)


base = git("merge-base", "HEAD", "master")
rng = f"{base}..HEAD"

# The commit that added the marker line to backlog.txt.
proto = git("log", "--format=%H", "-S", MARKER, "--", "backlog.txt")
proto_commits = [c for c in proto.splitlines() if c]
if not proto_commits:
    fail("no commit introduces the pre-registration entry into backlog.txt")
proto_sha = proto_commits[-1]  # oldest introducing commit
print(f"protocol commit: {proto_sha[:12]}")

# Every commit on this branch that touches an implementation file.
impl_log = git("log", "--format=%H", "--reverse", rng, "--", *IMPL)
impl_commits = [c for c in impl_log.splitlines() if c]
if not impl_commits:
    fail(
        "no implementation commit touches tracker.py or cron.py on this branch; "
        "G1 cannot pass vacuously -- the ordering is only meaningful once the "
        "implementation exists"
    )
first_impl = impl_commits[0]
print(f"first implementation commit: {first_impl[:12]}")

if proto_sha == first_impl:
    fail("the protocol and the implementation are in the SAME commit")

anc = subprocess.run(
    ["git", "merge-base", "--is-ancestor", proto_sha, first_impl],
    cwd=ROOT,
    capture_output=True,
)
if anc.returncode != 0:
    fail("the protocol commit is not an ancestor of the first implementation commit")

# The protocol commit must not itself carry implementation changes.
# `-z` + NUL split, not .split(): a filename containing a space would silently
# become two entries and the membership test would miss it.
_names = git("show", "--name-only", "-z", "--format=", proto_sha)
touched = [f for f in _names.split(chr(0)) if f]
bad = sorted(set(touched) & set(IMPL))
if bad:
    fail(f"the protocol commit also changes implementation files: {bad}")

# THE CONVERSE, which the first version never checked. G1's English says the
# pre-commitment is provable from git history; that is only true if the
# protocol text has not moved since. `3563cd31` -- the first implementation
# commit -- added 28 lines to backlog.txt, and this gate printed PASS anyway,
# because only the introduction of the title line was tracked. A later commit
# could rewrite the threshold, N_KILL or the frozen coefficients and nothing
# here would notice.
#
# Post-protocol edits to backlog.txt are ALLOWED but must be declared, so an
# honest addendum is possible and a silent rewrite is not.
DECLARED_EDITS = {
    # sha prefix -> what it added, and why it does not change a commitment
    "3563cd31": "YES-branch addendum: a measured consequence of the frozen "
                "coefficients, disclosed, additive, changes no commitment",
}
later = [c for c in git(
    "log", "--format=%H", "--reverse", f"{proto_sha}..HEAD", "--", "backlog.txt"
).splitlines() if c]
undeclared = [c for c in later if c[:8] not in DECLARED_EDITS]
if undeclared:
    fail(
        "commit(s) after the pre-registration edit backlog.txt without being "
        "declared in DECLARED_EDITS -- the protocol text is no longer the text "
        "that was pre-committed: "
        + ", ".join(c[:8] for c in undeclared)
    )
for c in later:
    print(f"declared post-protocol backlog edit: {c[:8]} -- {DECLARED_EDITS[c[:8]]}")

print("GATE_G1_PASS")
