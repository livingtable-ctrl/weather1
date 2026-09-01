"""Gate the SINGLETON figures -- those stated exactly once in the document.

A figure that appears twice is at least cross-checkable against itself; the
--restatements gate exploits that. A figure stated ONCE has no such check, so
it is guarded only if something derives it. `.unlazy/singleton_report.py`
intersected singleton-ness with mutation coverage and found 47 that nothing
reacted to.

These are gated by CLUSTER -- whole table columns rather than one figure at a
time -- because that is the only way the count actually falls and because a
column derivation cannot pass while an individual cell is wrong.

READ-ONLY.
"""

from __future__ import annotations

import math
import re
import statistics
from collections import defaultdict

from audit_handoff import TOL, _core_rows_ct, _section, con, text
from audit_handoff_ext import _per, fast_auc


def _se_auc(a: float, n1: int, n0: int) -> float:
    q1 = a / (2 - a)
    q2 = 2 * a * a / (1 + a)
    return math.sqrt(
        (a * (1 - a) + (n1 - 1) * (q1 - a * a) + (n0 - 1) * (q2 - a * a)) / (n1 * n0)
    )


def _auc_se(pairs) -> tuple[float | None, float]:
    n1 = sum(1 for _p, y in pairs if y == 1)
    n0 = len(pairs) - n1
    a = fast_auc(pairs)
    if a is None or not n1 or not n0:
        return None, float("nan")
    return a, _se_auc(a, n1, n0)


def _cmp(
    fails: list, label: str, actual: float | None, claimed: float, tol: float
) -> None:
    if actual is None or abs(actual - claimed) > tol:
        fails.append(f"{label}: derived {actual} but document says {claimed}")


def check_singletons() -> list[str]:
    fails: list[str] = []
    rows = _core_rows_ct()
    checked = 0

    # ---- market difference-in-differences line -----------------------------
    mm = re.search(
        r"market, MayJun - JulAug = -([0-9.]+), SE ([0-9.]+), z = -([0-9.]+)", text()
    )
    if not mm:
        fails.append("market DiD line: not found")
    else:
        v = {}
        for p_ in ("MayJun", "JulAug"):
            pairs = [
                (mp, float(y))
                for m, _op, mp, y, _ct, _tk in rows
                if _per(m) == p_ and mp is not None
            ]
            v[p_] = _auc_se(pairs)
        if v["MayJun"][0] is None or v["JulAug"][0] is None:
            fails.append("market DiD: a period has no usable rows")
            return fails
        d = v["MayJun"][0] - v["JulAug"][0]
        sd = math.sqrt(v["MayJun"][1] ** 2 + v["JulAug"][1] ** 2)
        _cmp(fails, "market DiD diff", -d, float(mm.group(1)), TOL)
        _cmp(fails, "market DiD SE", sd, float(mm.group(2)), TOL)
        _cmp(fails, "market DiD z", -(d / sd), float(mm.group(3)), 0.005)
        checked += 3

    # ---- prose restatement of the stratified AUCs --------------------------
    pm = re.search(r"\(n=110, AUC ([0-9.]+)\) and `above` \(n=52, ([0-9.]+)\)", text())
    if not pm:
        fails.append("stratified prose restatement: not found")
    else:
        g: dict[tuple, list] = defaultdict(list)
        for m, op, _mp, y, ct, _tk in rows:
            g[(_per(m), ct)].append((op, float(y)))
        _cmp(
            fails,
            "prose between MayJun",
            fast_auc(g[("MayJun", "between")]),
            float(pm.group(1)),
            0.0006,
        )
        _cmp(
            fails,
            "prose above MayJun",
            fast_auc(g[("MayJun", "above")]),
            float(pm.group(2)),
            0.0006,
        )
        checked += 2

    # ---- the pooled SE quoted for the within-`above` comparison ------------
    sm = re.search(
        r"the difference SE is ~([0-9]+\.[0-9]+), so \*\*z is about ([0-9]+\.[0-9]+)",
        text(),
    )
    if not sm:
        fails.append("within-above SE sentence: not found")
    else:
        g2: dict[str, list] = defaultdict(list)
        for m, op, _mp, y, ct, _tk in rows:
            if ct == "above":
                g2[_per(m)].append((op, float(y)))
        a1, s1 = _auc_se(g2["MayJun"])
        a2, s2 = _auc_se(g2["JulAug"])
        if a1 is None or a2 is None:
            fails.append("within-above: a stratum has no usable rows")
        else:
            sd = math.sqrt(s1 * s1 + s2 * s2)
            _cmp(fails, "within-above diff SE", sd, float(sm.group(1)), 0.001)
            _cmp(fails, "within-above z", (a1 - a2) / sd, float(sm.group(2)), 0.01)
            checked += 2

    # ---- traded-subset table: SE and z columns -----------------------------
    import json

    from audit_handoff import DB

    pt = json.loads((DB.parent / "paper_trades.json").read_text(encoding="utf-8"))
    pt = pt if isinstance(pt, list) else pt.get("trades", pt)
    if isinstance(pt, dict):
        pt = list(pt.values())
    traded = {r["ticker"] for r in pt if r.get("ticker")}
    scope = _section(
        "Restricting BOTH halves to rows that have a paper trade", fails, "traded"
    )
    for who in ("model", "market"):
        tm = re.search(
            rf"\| Jul-Aug \| {who} \| \*{{0,2}}\d+\*{{0,2}} \| \*{{0,2}}[0-9.]+\*{{0,2}} \| ([0-9.]+) \| \*{{0,2}}([+-][0-9.]+)\*{{0,2}} \|",
            scope,
        )
        if not tm:
            fails.append(f"traded-subset {who}: SE/z cells not found")
            continue
        pairs = [
            ((op if who == "model" else mp), float(y))
            for m, op, mp, y, _ct, tk in rows
            if _per(m) == "JulAug"
            and tk in traded
            and (mp is not None or who == "model")
        ]
        a, se = _auc_se(pairs)
        if a is None:
            fails.append(f"traded {who}: no usable rows")
            continue
        _cmp(fails, f"traded {who} SE", se, float(tm.group(1)), TOL)
        _cmp(fails, f"traded {who} z", (a - 0.5) / se, float(tm.group(2)), 0.005)
        checked += 2

    # ---- Brier / edge / accuracy table -------------------------------------
    bscope = _section(
        "| month | n | Brier(model) | Brier(market) | edge | accuracy |", fails, "brier"
    )
    # ENSEMBLE ONLY. The document's Brier table sits beside the ensemble
    # confidence table and its n column (51/48/56/70) is the ensemble count --
    # deriving it over all methods gives 147 for June and fails, which is the
    # gate catching the CHECK, not the document.
    bym: dict[str, list] = defaultdict(list)
    with con() as c:
        for m, op, mp, y in c.execute(
            """SELECT strftime('%Y-%m', p.predicted_at), p.our_prob,
                      p.market_prob, o.settled_yes
               FROM predictions p JOIN outcomes_valid o ON o.ticker = p.ticker
               WHERE o.settled_yes IN (0,1) AND p.our_prob IS NOT NULL
                 AND p.market_prob IS NOT NULL AND p.method = 'ensemble'
                 AND (p.ticker LIKE 'KXHIGH%' OR p.ticker LIKE 'KXLOWT%')"""
        ).fetchall():
            bym[m].append((op, mp, float(y)))
    for key in ("2026-05", "2026-06", "2026-07", "2026-08"):
        bm = re.search(
            rf"\| {key} \| (\d+) \| ([0-9.]+) \| ([0-9.]+) \| (-[0-9.]+) \| ([0-9.]+)% \|",
            bscope,
        )
        if not bm:
            fails.append(f"brier table {key}: row not found")
            continue
        bv = bym[key]
        model = statistics.fmean((pp - yy) ** 2 for pp, _q, yy in bv)
        market = statistics.fmean((qq - yy) ** 2 for _p, qq, yy in bv)
        acc = statistics.fmean(
            1.0 if (pp >= 0.5) == (yy == 1) else 0.0 for pp, _q, yy in bv
        )
        if len(bv) != int(bm.group(1)):
            fails.append(f"brier {key} n: {len(bv)} doc says {bm.group(1)}")
        _cmp(fails, f"brier {key} model", model, float(bm.group(2)), TOL)
        _cmp(fails, f"brier {key} market", market, float(bm.group(3)), TOL)
        _cmp(fails, f"brier {key} edge", market - model, -float(bm.group(4)[1:]), TOL)
        _cmp(fails, f"brier {key} accuracy", 100 * acc, float(bm.group(5)), 0.06)
        checked += 5

    # ---- the Brier SCOPE sentence (ensemble vs all methods) ----------------
    em = re.search(
        r"specifically\*\* \(([0-9.]+) -> ([0-9.]+)\); pooled across ALL methods it slightly\s*\n?\s*worsens \(([0-9.]+) -> ([0-9.]+)\)",
        text(),
    )
    if not em:
        fails.append("Brier scope sentence: not found")
    else:
        with con() as c:
            ens = c.execute(
                """SELECT strftime('%Y-%m', p.predicted_at), p.our_prob, o.settled_yes
                   FROM predictions p JOIN outcomes_valid o ON o.ticker = p.ticker
                   WHERE o.settled_yes IN (0,1) AND p.our_prob IS NOT NULL
                     AND p.method='ensemble'
                     AND (p.ticker LIKE 'KXHIGH%' OR p.ticker LIKE 'KXLOWT%')"""
            ).fetchall()
        be: dict[str, list] = defaultdict(list)
        for m, op, y in ens:
            be[_per(m)].append((op, float(y)))
        ba: dict[str, list] = defaultdict(list)
        for m, op, _mp, y, _ct, _tk in rows:
            ba[_per(m)].append((op, float(y)))
        for lbl, bsrc, grp_a, grp_b in (
            ("ensemble", be, 1, 2),
            ("all-methods", ba, 3, 4),
        ):
            for per, grp in (("MayJun", grp_a), ("JulAug", grp_b)):
                mean_b = statistics.fmean((pp - yy) ** 2 for pp, yy in bsrc[per])
                _cmp(
                    fails, f"brier-scope {lbl} {per}", mean_b, float(em.group(grp)), TOL
                )
                checked += 1

    # ---- obs-split confidence ----------------------------------------------
    om = re.search(
        r"CONTAINING obs have LOWER mean confidence \(([0-9.]+), n=(\d+)\) than blends\s*\n?\s*without it \(([0-9.]+), n=(\d+)\)",
        text(),
    )
    if not om:
        fails.append("obs-split confidence sentence: not found")
    else:
        with con() as c:
            osrc = c.execute(
                """SELECT our_prob, blend_sources FROM predictions
                   WHERE our_prob IS NOT NULL AND blend_sources IS NOT NULL
                     AND method='ensemble' AND predicted_at >= '2026-05-01'
                     AND (ticker LIKE 'KXHIGH%' OR ticker LIKE 'KXLOWT%')"""
            ).fetchall()
        with_obs: list[float] = []
        without: list[float] = []
        for op, bs in osrc:
            try:
                has = "obs" in json.loads(bs)
            except Exception:
                has = "obs" in str(bs)
            (with_obs if has else without).append(abs(op - 0.5))
        _cmp(
            fails,
            "obs-present conf",
            statistics.fmean(with_obs),
            float(om.group(1)),
            TOL,
        )
        _cmp(
            fails, "obs-absent conf", statistics.fmean(without), float(om.group(3)), TOL
        )
        if len(with_obs) != int(om.group(2)):
            fails.append(f"obs-present n: {len(with_obs)} doc says {om.group(2)}")
        if len(without) != int(om.group(4)):
            fails.append(f"obs-absent n: {len(without)} doc says {om.group(4)}")
        checked += 4

    if checked < 20:
        fails.append(f"VACUITY FLOOR: only {checked} figures derived in batch 1")
    return fails


def check_singletons_2() -> list[str]:
    """Second singleton batch: the daily table, the raw_prob mean column,
    the conf(raw_prob) column, and the Brier-alert values quoted from
    backlog.txt.

    Separate function, not an extension of check_singletons: appending into
    that one reused local names across unrelated blocks and produced eight
    mypy shadowing errors. Each batch gets its own scope.
    """
    fails: list[str] = []
    checked = 0

    # ---- the daily our_prob table (20 singleton figures live here) ---------
    dscope = _section("| date | n | conf | our_prob values |", fails, "daily")
    with con() as c:
        drows = c.execute(
            """SELECT date(predicted_at), our_prob FROM predictions
               WHERE method='ensemble' AND our_prob IS NOT NULL
                 AND predicted_at >= '2026-06-25' AND predicted_at < '2026-07-10'
                 AND (ticker LIKE 'KXHIGH%' OR ticker LIKE 'KXLOWT%')"""
        ).fetchall()
    byday: dict[str, list] = defaultdict(list)
    for d, p_ in drows:
        byday[d].append(p_)
    for dm in re.finditer(
        r"\| (2026-\d\d-\d\d) \| (\d+) \| \*{0,2}([0-9.]+)\*{0,2} \| ([^|]+)\|", dscope
    ):
        day, n, conf, vals = (
            dm.group(1),
            int(dm.group(2)),
            float(dm.group(3)),
            dm.group(4),
        )
        day_rows = byday.get(day, [])
        if len(day_rows) != n:
            fails.append(f"daily {day} n: {len(day_rows)} doc says {n}")
            continue
        _cmp(
            fails,
            f"daily {day} conf",
            statistics.fmean(abs(x - 0.5) for x in day_rows),
            conf,
            TOL,
        )
        checked += 1
        # every listed probability must actually be one of that day's rows
        for lit in re.findall(r"([0-9]+\.[0-9]{3})", vals):
            if not any(abs(x - float(lit)) < 5e-4 for x in day_rows):
                fails.append(
                    f"daily {day}: listed value {lit} is not among that day's rows"
                )
            checked += 1

    # ---- raw_prob magnitude table: the MEAN column -------------------------
    rscope = _section("Measured magnitude of `|our_prob - raw_prob|`", fails, "rawmean")
    with con() as c:
        rr = c.execute(
            """SELECT strftime('%Y-%m', predicted_at), ABS(our_prob - raw_prob)
               FROM predictions
               WHERE our_prob IS NOT NULL AND raw_prob IS NOT NULL
                 AND method='ensemble' AND predicted_at >= '2026-05-01'
                 AND (ticker LIKE 'KXHIGH%' OR ticker LIKE 'KXLOWT%')"""
        ).fetchall()
    byr: dict[str, list] = defaultdict(list)
    for m, d in rr:
        byr[m].append(d)
    for rm in re.finditer(
        r"\| (2026-\d\d) \| \d+ \| [0-9.e-]+ \| ([0-9.e-]+) \| [0-9.]+ \| \d+ \|",
        rscope,
    ):
        vr = byr.get(rm.group(1), [])
        if vr:
            _cmp(
                fails,
                f"rawprob {rm.group(1)} mean",
                statistics.fmean(vr),
                float(rm.group(2)),
                5e-5,
            )
            checked += 1

    # ---- conf(raw_prob) column of the confidence table ---------------------
    cscope = _section("## Superseded: the original Finding 1 numbers", fails, "confraw")
    with con() as c:
        cr = c.execute(
            """SELECT strftime('%Y-%m', p.predicted_at), p.raw_prob
               FROM predictions p JOIN outcomes_valid o ON o.ticker = p.ticker
               WHERE o.settled_yes IN (0,1) AND p.raw_prob IS NOT NULL
                 AND p.method='ensemble'
                 AND (p.ticker LIKE 'KXHIGH%' OR p.ticker LIKE 'KXLOWT%')"""
        ).fetchall()
    byc: dict[str, list] = defaultdict(list)
    for m, rp in cr:
        byc[m].append(abs(rp - 0.5))
    for cm in re.finditer(
        r"\| (2026-\d\d) \| \d+ \| [0-9.]+ \| ([0-9.]+) \| [0-9.]+% \|", cscope
    ):
        vc = byc.get(cm.group(1), [])
        if vc:
            _cmp(
                fails,
                f"conf(raw) {cm.group(1)}",
                statistics.fmean(vc),
                float(cm.group(2)),
                TOL,
            )
            checked += 1

    # ---- the Brier-alert values quoted from backlog.txt --------------------
    am = re.search(r"threshold at \*\*([0-9.]+) and ([0-9.]+)\*\*", text())
    if am:
        from audit_handoff import ROOT as _R

        bl = (_R / "backlog.txt").read_text(encoding="utf-8", errors="replace")
        for g in (1, 2):
            if am.group(g) not in bl:
                fails.append(
                    f"quoted Brier alert {am.group(g)} is not present in backlog.txt"
                )
            checked += 1

    if checked < 20:
        fails.append(f"VACUITY FLOOR: only {checked} figures derived in batch 2")
    return fails


SINGLETON_CHECKS = {
    "--singletons": ("HANDOFF_SINGLETONS_OK", check_singletons),
    "--singletons2": ("HANDOFF_SINGLETONS2_OK", check_singletons_2),
}
