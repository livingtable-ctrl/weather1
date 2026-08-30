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
sys.path.insert(0, str(ROOT))
import tracker  # noqa: E402

TEXT = (ROOT / "backlog.txt").read_text(encoding="utf-8")
MARKER = "FORWARD-VALIDATION PROTOCOL FOR THE PRICE-RECALIBRATION RULE"

failures: list[str] = []


def need(cond: bool, msg: str) -> None:
    if not cond:
        failures.append(msg)


def flat(s: str) -> str:
    """Collapse whitespace so a line-wrapped phrase still matches.

    backlog.txt is hard-wrapped at ~78 columns, so "the seventh threshold" can
    land with a newline inside it. A raw substring test then fails on text that
    is plainly present, which makes the gate fail for the wrong reason -- and
    would tempt someone to reword the entry to suit the checker.
    """
    return re.sub(r"\s+", " ", s)


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
need(bool(flat(s2)), "section 2 (what gets logged per pick) missing")
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
    need(col in flat(s2), f"per-pick log field not specified: {col}")
need(
    "immutable" in flat(s2).lower() and "upsert" in flat(s2).lower(),
    "section 2 must state the rows are immutable and contrast with the upsert",
)
need(
    "sigmoid(a + b*logit(mid))" in s2 or "a + b*logit" in flat(s2),
    "the decision rule's recalibration formula is not stated",
)
need(
    "side = YES if recalibrated > mid" in flat(s1),
    "the side rule is not pre-committed in section 1",
)
need(
    "thr = 0.05" in s1 and "0.08" in flat(s1),
    "the frozen threshold and the treatment of the 0.08 arm are not stated",
)
need(
    re.search(r"a = -0\.12856", flat(s1)) is not None
    and re.search(r"b = \+1\.33635", flat(s1)) is not None,
    "the frozen coefficients are not pinned in section 1",
)

# --- requirement 2: the multiple-testing haircut, all three papers read -------
s4 = section(4)
need(bool(flat(s4)), "section 4 (the haircut) missing")
need("GELMAN & LOKEN" in flat(s4), "Gelman & Loken not cited")
need("HARVEY & LIU" in flat(s4), "Harvey & Liu not cited")
need("BAILEY & LOPEZ DE PRADO" in flat(s4), "deflated Sharpe not cited")
need(
    "T(y; phi(y))" in flat(s4),
    "Gelman & Loken cited without their procedure-#3 notation -- reads as located, not read",
)
need(
    "p_BON = min(M * p_val, 1)" in flat(s4),
    "Harvey & Liu cited without the Haircut_SR.m formula",
)
need(
    "Euler-Mascheroni" in s4 and "Z^-1[1-1/N]" in flat(s4),
    "deflated Sharpe cited without its expected-maximum formula",
)
need("MinBTL" in flat(s4), "MinBTL neither used nor explicitly declined")
need("M FOR THIS RULE = 12" in flat(s4), "the declared search size M is not pinned")
need("2.8653" in flat(s4), "the Bonferroni t-cut is not stated")
need(
    "assumed the N trials to be independent" in flat(s4),
    "the noise floor is quoted without the source's own independence caveat, "
    "which the entry contradicts two paragraphs earlier",
)

# --- requirement 3: the derived minimum sample, and independence -------------
s5 = section(5)
need(bool(flat(s5)), "section 5 (the sample floor) missing")
need(
    f"N_KILL = {tracker.PRICE_RECAL_LOOK_2:,}" in flat(s5),
    "the pre-committed sample floor is not pinned, or disagrees with "
    "tracker.PRICE_RECAL_LOOK_2 -- an earlier draft transcribed the look points "
    "independently into three files, so tracker could have held a different "
    "number with every gate still green",
)
need(
    "CORRECTED" in s5 and "0.42024" in flat(s5),
    "section 5 must show the corrected sd, and say it is a correction",
)
need(
    "power statement, not an exclusion" in flat(s5),
    "the corollary must not describe a null as EXCLUDING the powered-against "
    "effect -- 80% power means it dies one time in five",
)
need(
    "n = ( (z_crit + z_power) * sd / delta )^2" in flat(s5),
    "the floor is asserted rather than derived from a stated formula",
)
need(
    "PICK COUNT, NOT A DAY COUNT" in flat(s5),
    "section 5 must say the horizon is a pick count, not a duration",
)
need(
    "cluster" in flat(s3).lower() and "(city, target_date)" in flat(s3),
    "the independent-observation unit is not defined in section 3",
)
need(
    "design effect" in flat(s3).lower(),
    "section 3 must address settled-count vs independent samples numerically",
)

# --- requirement 4: stopping rule and no-peeking ------------------------------
s6 = section(6)
need(bool(flat(s6)), "section 6 (stopping / no-peeking) missing")
need("EXACTLY TWO LOOKS" in flat(s6), "the number of looks is not pre-committed")
need(
    str(tracker.PRICE_RECAL_LOOK_1) in s6
    and f"{tracker.PRICE_RECAL_LOOK_2:,}" in flat(s6),
    "the two look points are not both stated, or disagree with tracker",
)
need(
    "target_date" in s3 and "CLUSTER = target_date" in flat(s3),
    "the primary cluster level is not pre-committed",
)
need(
    "wild cluster bootstrap-t" in flat(s3),
    "no rule for the small-cluster case, where the normal approximation the "
    "decision rests on is biased toward falsely clearing the bar",
)
need("WHAT KILLS IT" in flat(s6), "no explicit kill condition")
need(
    "subgroup list is empty" in flat(s6),
    "no rule against re-cutting the data by subgroup",
)
need(
    "seventh threshold" in flat(s6),
    "no rule against re-clustering after seeing the data -- worth 0.19 in z",
)
need(
    "non-accrual" in flat(s6),
    "no deadline -- a horizon that can extend forever never judges",
)
need(
    "ambiguous" in s6 and "FAILED" in flat(s6),
    "no pre-committed tie-break for an ambiguous result",
)

if failures:
    for f in failures:
        print(f"FAIL: {f}")
    sys.exit(1)
print("GATE_G2_PASS")
