"""G1: the protocol was committed before any implementation, and has not moved.

Two independent properties, proved separately:

  ORDERING -- the commit that introduced the pre-registration into backlog.txt
  precedes the first commit touching tracker.py or cron.py, and does not itself
  carry implementation changes.

  IMMUTABILITY -- the protocol entry's BYTES at HEAD hash to a value recorded
  here. Every deliberate change to them is listed with its reason.

WHY IMMUTABILITY IS CONTENT-HASHED, NOT COMMIT-TRACKED. An earlier version
listed every commit touching backlog.txt and required each to be declared. That
was wrong twice. It fails on any UNRELATED backlog entry -- the file holds
hundreds, and prepending one has nothing to do with the protocol -- so it went
red the moment a note about a circuit breaker was filed. And it never looked at
the protocol text at all, so a commit could declare itself "typo fix" while
rewriting N_KILL. Hashing the entry's own bytes binds the thing the gate claims
to protect and ignores everything else in a 3.2 MB file.

WHY THE FORK POINT IS FROZEN. An earlier version searched `merge-base(HEAD,
master)..HEAD` for implementation commits, which broke after merge -- the range
goes empty. Re-anchoring on `proto_sha..HEAD` fixed that and REMOVED THE GATE'S
TEETH: that range excludes everything reachable from the protocol commit, so an
implementation written first and back-dated behind a later pre-registration
becomes invisible and the ancestry check can never fail. That is the exact
fraud this gate exists to detect. FORK_SHA is the pre-merge fork point, frozen;
it is permanent, survives the merge, and restores the check.
"""

from __future__ import annotations

import hashlib
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
MARKER = "FORWARD-VALIDATION PROTOCOL FOR THE PRICE-RECALIBRATION RULE"
IMPL = ("tracker.py", "cron.py")

# Frozen fork point, single-sourced in _fork.py -- three gates need it and a
# retyped constant drifting apart is the defect this session spent three review
# rounds removing.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _fork import FORK_SHA  # noqa: E402

# SHA-256 of the protocol entry's bytes at HEAD. Update ONLY alongside an entry
# in PROTOCOL_CHANGES -- the hash is the binding, the list is the reason.
EXPECTED_ENTRY_SHA256 = (
    "4ebe969fd5b53821b1af1ea38c0053f6e900ad71007eaf20e031bb0f62b80fc2"
)

# Every deliberate change to the protocol text, newest last. All four were made
# BEFORE the first pick was logged; the entry caps that argument and it is now
# spent. Anything after the first logged row is a re-registration under a new
# protocol_version, not an edit.
#
# 2026-08-30: a TERMINAL abandonment marker was briefly added here and then
# removed the same day. The sunset it recorded was decided on a false premise
# -- that the METAR lock's paper profit came from a bug the June guard fixed.
# Splitting the 89 lock trades by that guard's own window showed the reverse:
# the bug window lost $72.40 and the surviving hours made $191.76. The entry
# is back to its sealed text, byte-identical, and this note is left in place
# because a hash that silently returned to a prior value would be the one
# thing this gate exists to make impossible to do quietly.
PROTOCOL_CHANGES = [
    "3563cd31 YES-branch addendum -- a measured consequence of the frozen "
    "coefficients, disclosed, additive, changes no commitment.",
    "3ecf7b16 round-1 review. N_KILL 1,340 -> 1,700, look 1 670 -> 850, "
    "M 10 -> 12, primary cluster (city,target_date) -> target_date.",
    "26f5f93c round-2 review. Floor re-DENOMINATED in distinct picks rather "
    "than logged rows; cluster justified by mechanism rather than by the z.",
    "e5b2d33e round-3 review, THE LAST PRE-CLOCK EDIT. Floor 1,700 -> 2,200 on "
    "a MEASURED 1.5c half-spread; pick price pinned to the first firing row; "
    "design-effect column defined and its negative in-sample ICC disclosed.",
]


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


# ---------------------------------------------------------------- ORDERING
proto = git("log", "--format=%H", "-S", MARKER, "--", "backlog.txt")
proto_commits = [c for c in proto.splitlines() if c]
if not proto_commits:
    fail("no commit introduces the pre-registration entry into backlog.txt")
proto_sha = proto_commits[-1]  # oldest introducing commit
print(f"protocol commit: {proto_sha[:12]}")

# THE TEETH: nothing may have implemented this before the protocol landed.
# Searched from the FROZEN fork, so a back-dated pre-registration is visible.
before = [
    c
    for c in git(
        "log", "--format=%H", f"{FORK_SHA}..{proto_sha}", "--", *IMPL
    ).splitlines()
    if c
]
if before:
    fail(
        "implementation commit(s) land BEFORE the pre-registration -- the "
        "protocol was not pre-committed: " + ", ".join(c[:8] for c in before)
    )
print(f"no implementation between {FORK_SHA} and the protocol commit")

impl_log = git("log", "--format=%H", "--reverse", f"{proto_sha}..HEAD", "--", *IMPL)
impl_commits = [c for c in impl_log.splitlines() if c]
if not impl_commits:
    fail(
        "no implementation commit touches tracker.py or cron.py after the "
        "protocol commit; G1 cannot pass vacuously -- the ordering is only "
        "meaningful once the implementation exists"
    )
print(f"first implementation commit: {impl_commits[0][:12]}")

# The protocol commit must not itself carry implementation changes.
# `-z` + NUL split, not .split(): a filename containing a space would silently
# become two entries and the membership test would miss it.
_names = git("show", "--name-only", "-z", "--format=", proto_sha)
touched = [f for f in _names.split(chr(0)) if f]
bad = sorted(set(touched) & set(IMPL))
if bad:
    fail(f"the protocol commit also changes implementation files: {bad}")

# ------------------------------------------------------------- IMMUTABILITY
TEXT = (ROOT / "backlog.txt").read_text(encoding="utf-8")
start = TEXT.find(MARKER)
if start < 0:
    fail("the pre-registration entry is no longer in backlog.txt")
nxt = re.search(r"\n\[(?:OPEN|DONE|CLOSED) ", TEXT[start:])
entry = TEXT[start : start + (nxt.start() if nxt else len(TEXT) - start)]
digest = hashlib.sha256(entry.encode("utf-8")).hexdigest()
print(f"protocol entry: {len(entry.encode('utf-8')):,} bytes, sha256 {digest[:16]}...")
if digest != EXPECTED_ENTRY_SHA256:
    fail(
        "THE PROTOCOL TEXT HAS CHANGED.\n"
        f"       expected {EXPECTED_ENTRY_SHA256}\n"
        f"       found    {digest}\n"
        "       If deliberate, add it to PROTOCOL_CHANGES with a reason and "
        "update EXPECTED_ENTRY_SHA256.\n"
        "       If the clock has started (any row in price_recal_shadow_log) "
        "it is NOT an edit -- it is a re-registration under a new "
        "protocol_version, and the old registration is marked FAILED first."
    )
for c in PROTOCOL_CHANGES:
    print(f"  declared change: {c[:76]}")

print("GATE_G1_PASS")
