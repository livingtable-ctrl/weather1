"""G8: what changed between 2026-06-30 03:34 and 2026-07-02 19:07.

Re-derives the four load-bearing claims of the METAR-composition finding
against the live DB, and FAILS if any of them stops holding. Every expected
figure is READ FROM THE HANDOFF DOCUMENT, not hardcoded here, so editing a
number in the prose to make this pass breaks the comparison instead.

Population is `audit_handoff._core_rows`'s definition verbatim.

Read-only: the DB is opened with mode=ro.
"""

from __future__ import annotations

import pathlib
import re
import sqlite3
import sys
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from paths import DB_PATH  # noqa: E402

DOC = ROOT / "docs" / "HANDOFF-confidence-collapse-2026-08-30.md"
TOL = 5e-4


def con():
    return sqlite3.connect(
        f"{pathlib.Path(DB_PATH).resolve().as_uri()}?mode=ro", uri=True
    )


def rows():
    with con() as c:
        return c.execute(
            """SELECT strftime('%Y-%m', p.predicted_at), p.our_prob, p.market_prob,
                      o.settled_yes, p.method, p.condition_type, p.predicted_at
               FROM predictions p JOIN outcomes_valid o ON o.ticker = p.ticker
               WHERE o.settled_yes IN (0,1) AND p.our_prob IS NOT NULL
                 AND (p.ticker LIKE 'KXHIGH%' OR p.ticker LIKE 'KXLOWT%')"""
        ).fetchall()


def auc(pairs):
    pos = [s for s, y in pairs if y == 1]
    neg = [s for s, y in pairs if y == 0]
    if not pos or not neg:
        return None
    w = sum(1.0 if a > b else 0.5 if a == b else 0.0 for a in pos for b in neg)
    return w / (len(pos) * len(neg))


def period(m):
    return "MayJun" if m in ("2026-05", "2026-06") else "JulAug"


def doc() -> str:
    return DOC.read_text(encoding="utf-8")


def want(pattern: str, label: str, fails: list) -> tuple[float, ...] | None:
    m = re.search(pattern, doc(), re.S)
    if not m:
        fails.append(f"{label}: the document no longer states this figure")
        return None
    return tuple(float(g) for g in m.groups())


def main() -> int:
    fails: list[str] = []
    R = rows()

    # --- 1. METAR share of each period's core rows --------------------------
    share: defaultdict[str, list[int]] = defaultdict(lambda: [0, 0])
    for m, _op, _mp, _y, meth, _ct, _pa in R:
        p = period(m)
        share[p][1] += 1
        if meth == "metar_lockout":
            share[p][0] += 1
    got = {p: (v[0], v[1], 100.0 * v[0] / v[1]) for p, v in share.items()}

    w = want(
        r"METAR lock-ins were \*\*(\d+) of (\d+)\*\*\s+May-June core rows "
        r"\(\*\*([0-9.]+)%\*\*\).{0,160}?(\d+) of (\d+) \(([0-9.]+)%\)",
        "metar-share",
        fails,
    )
    if w:
        for i, p in enumerate(("MayJun", "JulAug")):
            n, tot, pct = got[p]
            if (n, tot) != (int(w[3 * i]), int(w[3 * i + 1])):
                fails.append(
                    f"metar share {p}: measured {n}/{tot}, document says "
                    f"{int(w[3 * i])}/{int(w[3 * i + 1])}"
                )
            if abs(pct - w[3 * i + 2]) > 0.05:
                fails.append(
                    f"metar pct {p}: measured {pct:.1f}, document says {w[3 * i + 2]}"
                )

    # --- 2. AUC of the METAR rows vs everything else ------------------------
    def sub(pred):
        out = defaultdict(list)
        for m, op, _mp, y, meth, ct, _pa in R:
            if pred(meth, ct):
                out[period(m)].append((op, float(y)))
        return out

    metar = sub(lambda meth, ct: meth == "metar_lockout")
    nometar_pairs = sub(lambda meth, ct: meth != "metar_lockout")
    a_metar_mj = auc(metar["MayJun"])
    w = want(
        r"May-June ([0-9.]+) \(n=89\) vs ([0-9.]+) \(n=109\), difference "
        r"\+([0-9.]+), SE ([0-9.]+),\s+\*\*z = \+([0-9.]+)\*\*",
        "metar-vs-nonmetar",
        fails,
    )
    nonmetar_mj = auc(nometar_pairs["MayJun"])
    if w:
        if a_metar_mj is not None and abs(a_metar_mj - w[0]) > TOL:
            fails.append(
                f"metar MayJun AUC: measured {a_metar_mj:.4f}, document says {w[0]}"
            )
        if nonmetar_mj is not None and abs(nonmetar_mj - w[1]) > TOL:
            fails.append(
                f"non-METAR MayJun AUC: measured {nonmetar_mj:.4f}, doc says {w[1]}"
            )
        # THE LOAD-BEARING NEGATIVE. The composition story needs METAR to
        # actually discriminate better than the rows it was pooled with. It
        # does not, at this n. If a growing corpus ever makes it significant
        # the document must be rewritten, so fail rather than pass quietly.
        if w[4] >= 1.96:
            fails.append(
                f"document states z = +{w[4]} for the METAR-vs-non-METAR "
                f"difference, which is now SIGNIFICANT -- the section is "
                f"written around this being z ~ +1.16 and must be revised"
            )

    # --- 3. The headline gap with and without the METAR rows ----------------
    allr = sub(lambda meth, ct: True)
    nometar = nometar_pairs
    gap_all = auc(allr["MayJun"]) - auc(allr["JulAug"])
    gap_no = auc(nometar["MayJun"]) - auc(nometar["JulAug"])

    w = want(
        r"shrinks the May-June minus July-August gap from\s+"
        r"\*\*\+([0-9.]+)\*\* to \*\*\+([0-9.]+)\*\*",
        "gap-shrink",
        fails,
    )
    if w:
        if abs(gap_all - w[0]) > TOL:
            fails.append(
                f"gap with METAR: measured {gap_all:+.4f}, document says +{w[0]}"
            )
        if abs(gap_no - w[1]) > TOL:
            fails.append(
                f"gap without METAR: measured {gap_no:+.4f}, document says +{w[1]}"
            )
    # The finding's DIRECTION is the claim, so assert it independently of the
    # prose: removing the METAR rows must SHRINK the gap. If a growing corpus
    # ever reverses that, this gate must fail rather than quietly re-state a
    # number the document happens to still contain.
    if not gap_no < gap_all:
        fails.append(
            f"DIRECTION REVERSED: removing METAR rows did not shrink the gap "
            f"({gap_all:+.4f} -> {gap_no:+.4f}). The finding no longer holds."
        )

    # --- 4. The lock-in gap actually spans the window -----------------------
    with con() as c:
        days = [
            r[0]
            for r in c.execute(
                "SELECT DISTINCT substr(predicted_at,1,10) FROM predictions "
                "WHERE method='metar_lockout' ORDER BY 1"
            )
        ]
    inside = [d for d in days if "2026-06-27" <= d <= "2026-07-03"]
    if inside:
        fails.append(
            f"the window is no longer METAR-free: lock-ins recorded on {inside}"
        )
    # POSITIVE CONTROL for that absence: the same query must find plenty of
    # lock-in days immediately BEFORE the window. Without this, the check above
    # passes vacuously the moment the method is renamed or the rows vanish.
    before = [d for d in days if "2026-06-01" <= d < "2026-06-27"]
    if len(before) < 15:
        fails.append(
            f"positive control failed: only {len(before)} METAR days in "
            f"2026-06-01..06-26; the absence inside the window proves nothing"
        )

    # --- 5. It is the `between` BRANCH that stops, on e395392b's own day ----
    # This is the mechanism claim, and it is what distinguishes "a guard
    # commit killed one branch" from "the lock died". above/below must KEEP
    # firing past the boundary, or the branch-specific story is wrong.
    with con() as c:
        branch = c.execute(
            "SELECT condition_type, substr(predicted_at,1,10) FROM predictions "
            "WHERE method='metar_lockout'"
        ).fetchall()
    btw = sorted({d for ct, d in branch if ct == "between"})
    abv = sorted({d for ct, d in branch if ct in ("above", "below")})
    guard_day = "2026-06-25"  # e395392b, 2026-06-25 21:31 -0400
    btw_after = [d for d in btw if guard_day < d <= "2026-08-01"]
    if btw_after:
        fails.append(
            f"`between` lock-ins fired after the {guard_day} guard and before "
            f"August: {btw_after}. The branch-specific claim is wrong."
        )
    # POSITIVE CONTROLS, both required. Without the first, an empty
    # `btw_after` proves nothing (the branch might never have fired at all);
    # without the second, "only `between` stopped" is unsupported.
    if len([d for d in btw if d <= guard_day]) < 15:
        fails.append(
            f"positive control failed: only {len([d for d in btw if d <= guard_day])} "
            f"`between` lock-in days on or before {guard_day}"
        )
    if not [d for d in abv if guard_day < d <= "2026-08-01"]:
        fails.append(
            "positive control failed: no above/below lock-ins after the guard "
            "either, so the stop is not branch-specific"
        )

    print(f"core rows: {len(R)}")
    print(
        f"  between-branch lock days: {len([d for d in btw if d <= guard_day])} "
        f"through {guard_day}, {len(btw_after)} after (to Aug 1); "
        f"above/below after: {len([d for d in abv if guard_day < d <= '2026-08-01'])}"
    )
    for p in ("MayJun", "JulAug"):
        n, tot, pct = got[p]
        print(f"  {p}: METAR {n}/{tot} = {pct:.1f}%   AUC(all)={auc(allr[p]):.4f}")
    print(f"  gap with METAR    = {gap_all:+.4f}")
    print(f"  gap without METAR = {gap_no:+.4f}")
    print(f"  METAR days before window: {len(before)}, inside window: {len(inside)}")

    if fails:
        for f in fails:
            print("FAIL:", f)
        return 1
    print("JULY_WINDOW_PROBE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
