"""G8: the scoped suite is not vacuous.

Mutates each guard of the decision rule, one at a time, and requires the scoped
test module to FAIL. A guard whose mutant survives is a guard the suite does not
actually test, and the gate above it certifies nothing.

SAFE REVERT. The original file bytes are held in memory and rewritten in a
finally block. `git checkout --` is never used: this worktree carries
uncommitted work, and reverting a mutation with git would discard it.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCOPED = "tests/test_price_recal_shadow_log.py"

# (file, needle, replacement, what the mutation breaks)
MUTANTS = [
    (
        "cron.py",
        "if abs(divergence) < _PRICE_RECAL_THRESHOLD:",
        "if abs(divergence) < 0.0:",
        "threshold gate disabled -- every market becomes a pick",
    ),
    (
        "cron.py",
        "if divergence > 0:",
        "if divergence < 0:",
        "side rule inverted",
    ),
    (
        "cron.py",
        "if not (0.0 < entry_exec < 1.0):",
        "if False:",
        "executable-price guard removed -- unfillable books enter the corpus",
    ),
    (
        "cron.py",
        "if ctype not in _PRICE_RECAL_CORE_TYPES:",
        "if ctype is None:",
        "core-type gate widened to precip/hurricane",
    ),
    (
        "cron.py",
        "if not ticker or not target_str:",
        "if not ticker:",
        "target_date guard removed -- the dedup index stops binding",
    ),
    (
        "cron.py",
        "if not (0.0 < mid < 1.0):",
        "if not (0.0 <= mid < 1.0):",
        "mid range gate widened to admit an unquoted book at mid=0",
    ),
    (
        "cron.py",
        "                entry_exec = yes_ask",
        "                entry_exec = mid",
        "YES entry priced at the mid instead of the ask",
    ),
    (
        "cron.py",
        "                entry_exec = 1.0 - yes_bid",
        "                entry_exec = 1.0 - mid",
        "NO entry priced at the mid instead of the executable NO ask",
    ),
    (
        "cron.py",
        "_PRICE_RECAL_FIT_B = 1.33635",
        "_PRICE_RECAL_FIT_B = 1.4871",
        "frozen slope replaced by the discovery's -- the pre-registration ends",
    ),
    (
        "cron.py",
        '"INSERT OR IGNORE INTO price_recal_shadow_log "',
        '"INSERT OR REPLACE INTO price_recal_shadow_log "',
        "rows stop being immutable -- a later cycle overwrites the pick",
    ),
    (
        "tracker.py",
        "WHERE  outcome IS NULL",
        "WHERE  1 = 1",
        "settlement stops being one-way -- a settled pick can be revised",
    ),
    (
        "tracker.py",
        "                         AND  o.settled_yes IN (0, 1)",
        "                         AND  o.settled_yes IS NOT NULL",
        "settlement admits a non-binary settled_yes",
    ),
    # ---- added after round 1: guards and arithmetic with no mutant before ----
    (
        "tracker.py",
        "                       SELECT 1 FROM outcomes_valid o",
        # Assembled rather than written literally: tests/test_disputed_row_guard
        # .py scans every .py in the repo for a raw un-viewed join against the
        # settlements table, and a mutation string is indistinguishable from the
        # real thing to a text scanner -- as was an earlier version of THIS
        # comment, which tripped the guard by naming the pattern it describes.
        # Weakening a repo-wide guard to accommodate tooling would be the wrong
        # trade, so the tooling avoids the literal instead.
        "                       SELECT 1 " + "FROM " + "outcomes o",
        "settlement reads the raw outcomes table, ingesting disputed rows",
    ),
    (
        "tracker.py",
        "PRICE_RECAL_LOOK_1 = 850",
        "PRICE_RECAL_LOOK_1 = 851",
        "look 1 drifts off half of look 2",
    ),
    (
        "tracker.py",
        "PRICE_RECAL_LOOK_2 = 1700",
        "PRICE_RECAL_LOOK_2 = 1699",
        "the pre-committed floor drifts below the derived one",
    ),
    (
        "tracker.py",
        "  SELECT DISTINCT COALESCE(city, '?' || ticker), target_date",
        "  SELECT DISTINCT target_date",
        "settled_events drops the city, collapsing distinct weather events",
    ),
    (
        "tracker.py",
        "COALESCE(city, '?' || ticker)",
        "city",
        "NULL cities collapse into one event (SQLite DISTINCT treats them equal)",
    ),
    (
        "tracker.py",
        "  FROM price_recal_shadow_log WHERE outcome IS NOT NULL)",
        "  FROM price_recal_shadow_log)",
        "settled_events counts unsettled picks",
    ),
    (
        "cron.py",
        "    if hasattr(target_date, \"date\") and callable(target_date.date):",
        "    if False:",
        "a datetime target_date yields a timestamp key, defeating dedup",
    ),
    (
        "cron.py",
        "    return text.split(\"T\", 1)[0]",
        "    return text",
        "an ISO-timestamp string opens a second key space",
    ),
    (
        "cron.py",
        'target_date = analysis.get("target_date") or enriched.get("_date")',
        'target_date = analysis.get("target_date")',
        "the enriched fallback is dropped, silently losing markets from the corpus",
    ),
    (
        "cron.py",
        "                        if analysis.get(\"days_out\") is not None",
        "                        if True",
        "a missing days_out is recorded as a genuine same-day pick",
    ),
]


# The content gates are part of the verification a mutant must break. G2 and G3
# assert the pre-committed constants against tracker and against the DB, so a
# mutation to PRICE_RECAL_LOOK_2 is caught there and nowhere in pytest. Leaving
# them out made those mutants look untested when they were merely tested by a
# different oracle.
CONTENT_GATES = ("check_protocol.py", "check_numbers.py")


def run_scoped() -> bool:
    """True when the scoped suite AND the content gates all pass."""
    r = subprocess.run(
        [sys.executable, "-m", "pytest", SCOPED, "-q", "-x", "--no-header", "-p",
         "no:cacheprovider"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if r.returncode != 0:
        return False
    for gate in CONTENT_GATES:
        g = subprocess.run(
            [sys.executable, str(ROOT / ".unlazy" / gate)],
            cwd=ROOT, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        )
        if g.returncode != 0:
            return False
    return True


print("baseline: ", end="", flush=True)
if not run_scoped():
    print("FAIL")
    print("FAIL: the scoped suite does not pass unmutated; mutation results "
          "would be meaningless")
    sys.exit(1)
print("passes")

survivors: list[str] = []
for fname, needle, repl, what in MUTANTS:
    path = ROOT / fname
    original = path.read_bytes()
    text = original.decode("utf-8")
    if needle not in text:
        print(f"FAIL: mutation anchor not found in {fname}: {needle!r}")
        survivors.append(f"{what} (ANCHOR MISSING)")
        continue
    if text.count(needle) != 1:
        print(f"FAIL: mutation anchor is not unique in {fname} "
              f"({text.count(needle)} matches): {needle!r}")
        survivors.append(f"{what} (ANCHOR AMBIGUOUS)")
        continue
    try:
        path.write_bytes(text.replace(needle, repl, 1).encode("utf-8"))
        killed = not run_scoped()
    finally:
        # In-memory revert. Never `git checkout --`: this worktree carries
        # uncommitted work that would be destroyed.
        path.write_bytes(original)
    print(f"  {'KILLED ' if killed else 'SURVIVED'}  {fname}: {what}")
    if not killed:
        survivors.append(what)

# The revert must be provably complete before anything else is trusted.
if not run_scoped():
    print("FAIL: the suite does not pass after reverting -- a mutation leaked")
    sys.exit(1)

if survivors:
    for s in survivors:
        print(f"FAIL: surviving mutant -- the suite does not test this: {s}")
    sys.exit(1)
print(f"all {len(MUTANTS)} mutants killed")
print("GATE_G8_PASS")
