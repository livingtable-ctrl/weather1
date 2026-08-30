"""G2: the protocol entry states all four things the brief demands.

Structural, not keyword-soup: each requirement is checked by locating its
numbered section inside the entry's own bounds and asserting the section
contains the specific commitment, not merely the topic word.
"""

from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
TEXT = (ROOT / "backlog.txt").read_text(encoding="utf-8")
MARKER = "FORWARD-VALIDATION PROTOCOL FOR THE PRICE-RECALIBRATION RULE"

failures: list[str] = []


def need(cond: bool, msg: str) -> None:
    if not cond:
        failures.append(msg)


start = TEXT.find(MARKER)
if start < 0:
    print("FAIL: pre-registration entry not found in backlog.txt")
    sys.exit(1)
# The entry runs to the next top-level "[OPEN " / "[DONE " bracket at column 0.
nxt = re.search(r"\n\[(?:OPEN|DONE|CLOSED) ", TEXT[start:])
entry = TEXT[start : start + (nxt.start() if nxt else len(TEXT) - start)]
print(f"entry length: {len(entry.splitlines())} lines")


def section(n: int) -> str:
    m = re.search(rf"^{n}\. .+$", entry, re.M)
    if not m:
        return ""
    after = entry[m.end() :]
    nm = re.search(r"^-{20,}\n^\d+\. ", after, re.M)
    return after[: nm.start()] if nm else after


# --- requirement 1: what gets logged per pick, and the decision rule ----------
s1, s2, s3 = section(1), section(2), section(3)
need(bool(s2), "section 2 (what gets logged per pick) missing")
for col in (
    "yes_bid",
    "yes_ask",
    "recal_prob",
    "divergence",
    "side",
    "entry_price_exec",
    "days_out",
    "outcome",
    "protocol_version",
):
    need(col in s2, f"per-pick log field not specified: {col}")
need(
    "immutable" in s2.lower() and "upsert" in s2.lower(),
    "section 2 must state the rows are immutable and contrast with the upsert",
)
need(
    "sigmoid(a + b*logit(mid))" in s2 or "a + b*logit" in s2,
    "the decision rule's recalibration formula is not stated",
)
need(
    "side = YES if recalibrated > mid" in s1,
    "the side rule is not pre-committed in section 1",
)
need(
    "thr = 0.05" in s1 and "0.08" in s1,
    "the frozen threshold and the treatment of the 0.08 arm are not stated",
)
need(
    re.search(r"a = -0\.12856", s1) is not None
    and re.search(r"b = \+1\.33635", s1) is not None,
    "the frozen coefficients are not pinned in section 1",
)

# --- requirement 2: the multiple-testing haircut, all three papers read -------
s4 = section(4)
need(bool(s4), "section 4 (the haircut) missing")
need("GELMAN & LOKEN" in s4, "Gelman & Loken not cited")
need("HARVEY & LIU" in s4, "Harvey & Liu not cited")
need("BAILEY & LOPEZ DE PRADO" in s4, "deflated Sharpe not cited")
need(
    "T(y; phi(y))" in s4,
    "Gelman & Loken cited without their procedure-#3 notation -- reads as located, not read",
)
need(
    "p_BON = min(M * p_val, 1)" in s4,
    "Harvey & Liu cited without the Haircut_SR.m formula",
)
need(
    "Euler-Mascheroni" in s4 and "Z^-1[1-1/N]" in s4,
    "deflated Sharpe cited without its expected-maximum formula",
)
need("MinBTL" in s4, "MinBTL neither used nor explicitly declined")
need("M FOR THIS RULE = 10" in s4, "the declared search size M is not pinned")
need("2.807" in s4, "the Bonferroni t-cut is not stated")

# --- requirement 3: the derived minimum sample, and independence -------------
s5 = section(5)
need(bool(s5), "section 5 (the sample floor) missing")
need("N_KILL = 1,340" in s5, "the pre-committed sample floor is not pinned")
need(
    "n = ( (z_crit + z_power) * sd / delta )^2" in s5,
    "the floor is asserted rather than derived from a stated formula",
)
need(
    "PICK COUNT, NOT A DAY COUNT" in s5,
    "section 5 must say the horizon is a pick count, not a duration",
)
need(
    "cluster" in s3.lower() and "(city, target_date)" in s3,
    "the independent-observation unit is not defined in section 3",
)
need(
    "design effect" in s3.lower(),
    "section 3 must address settled-count vs independent samples numerically",
)

# --- requirement 4: stopping rule and no-peeking ------------------------------
s6 = section(6)
need(bool(s6), "section 6 (stopping / no-peeking) missing")
need("EXACTLY TWO LOOKS" in s6, "the number of looks is not pre-committed")
need("670" in s6 and "1,340" in s6, "the two look points are not both stated")
need("WHAT KILLS IT" in s6, "no explicit kill condition")
need(
    "subgroup list is empty" in s6,
    "no rule against re-cutting the data by subgroup",
)
need(
    "non-accrual" in s6,
    "no deadline -- a horizon that can extend forever never judges",
)
need(
    "ambiguous" in s6 and "FAILED" in s6,
    "no pre-committed tie-break for an ambiguous result",
)

if failures:
    for f in failures:
        print(f"FAIL: {f}")
    sys.exit(1)
print("GATE_G2_PASS")
