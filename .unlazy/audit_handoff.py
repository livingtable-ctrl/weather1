"""Runnable audit oracle for docs/HANDOFF-confidence-collapse-2026-08-30.md.

The handoff is a PROMPT: it will be pasted into a session with no access to
the conversation that produced it. Its only value is that a stranger acting on
it reaches correct conclusions. These checks test that property.

Written because the 2026-08-30 audit declared G1/G3/G7 as runnable gates and
then verified them ad hoc, leaving the ledger unreproducible. That was logged
as HANDOFF REQUIRED. This is the discharge.

READ-ONLY: opens the DB with mode=ro and never writes.

Usage: python .unlazy/audit_handoff.py --numbers | --commits | --citations
                                       | --contradictions | --populations
                                       | --rederive | --all
"""

from __future__ import annotations

import math
import pathlib
import re
import sqlite3
import statistics
import subprocess
import sys
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "HANDOFF-confidence-collapse-2026-08-30.md"
# paths.py resolves data/ to the MAIN clone, not the worktree.
sys.path.insert(0, str(ROOT))
import paths  # noqa: E402

DB = pathlib.Path(paths.DB_PATH)
TOL = 5e-4  # figures are quoted to 4dp


def con():
    return sqlite3.connect("file:" + DB.as_posix() + "?mode=ro", uri=True)


def text() -> str:
    return DOC.read_text(encoding="utf-8")


def _auc(pairs):
    pos = [p for p, y in pairs if y == 1]
    neg = [p for p, y in pairs if y == 0]
    if not pos or not neg:
        return None, 0, 0
    w = sum(1.0 if a > b else 0.5 if a == b else 0.0 for a in pos for b in neg)
    return w / (len(pos) * len(neg)), len(pos), len(neg)


def _se_auc(a, n1, n0):
    q1 = a / (2 - a)
    q2 = 2 * a * a / (1 + a)
    return math.sqrt(
        (a * (1 - a) + (n1 - 1) * (q1 - a * a) + (n0 - 1) * (q2 - a * a)) / (n1 * n0)
    )


def _doc_num(pattern: str, label: str, fails: list) -> float | None:
    """Extract ONE number the document asserts. Missing anchor is a FAILURE.

    The gates must read their expectations FROM the document, not hold their
    own copy. A hardcoded expectation makes the gate vacuous with respect to
    the doc: mutation testing on 2026-08-30 changed four figures in the text
    and every --numbers check still passed, because it was only ever
    comparing the database against constants in this file.
    """
    m = re.search(pattern, text())
    if not m:
        fails.append(f"{label}: anchor not found in document (pattern {pattern!r})")
        return None
    return float(m.group(1))


def _section(start_marker: str, fails: list, label: str) -> str:
    """Slice the doc from a heading/anchor to the next heading.

    Scoping matters: an unscoped regex for a table row matched the HEADLINE
    AUC table instead of the traded-subset table during the 2026-08-30
    hardening, silently comparing the wrong numbers.
    """
    t = text()
    i = t.find(start_marker)
    if i < 0:
        fails.append(f"{label}: section anchor {start_marker!r} not found")
        return ""
    j = t.find(chr(10) + "## ", i + len(start_marker))
    return t[i : j if j > 0 else len(t)]


def _core_rows():
    with con() as c:
        return c.execute(
            """SELECT strftime('%Y-%m', p.predicted_at), p.our_prob, p.market_prob,
                      o.settled_yes, p.ticker
               FROM predictions p JOIN outcomes_valid o ON o.ticker = p.ticker
               WHERE o.settled_yes IN (0,1) AND p.our_prob IS NOT NULL
                 AND (p.ticker LIKE 'KXHIGH%' OR p.ticker LIKE 'KXLOWT%')"""
        ).fetchall()


def check_numbers() -> list[str]:
    """Re-derive the load-bearing figures the document asserts."""
    fails: list[str] = []
    rows = _core_rows()

    # --- the headline AUC table ---------------------------------------------
    g: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for m, op, mp, y, _tk in rows:
        per = "MayJun" if m in ("2026-05", "2026-06") else "JulAug"
        g[per]["model"].append((op, float(y)))
        if mp is not None:
            g[per]["market"].append((mp, float(y)))
    # Expectations are READ FROM THE DOCUMENT so that editing a figure in the
    # text fails this gate. Row shape: | May-Jun | **model** | 198 | **0.6828** | 0.0377 |
    want = {}
    for per, lbl, who in (
        ("MayJun", "May-Jun", "model"),
        ("MayJun", "May-Jun", "market"),
        ("JulAug", "Jul-Aug", "model"),
        ("JulAug", "Jul-Aug", "market"),
    ):
        row = rf"\| {lbl} \| \*{{0,2}}{who}\*{{0,2}} \| (\d+) \| \*{{0,2}}([0-9.]+)\*{{0,2}} \| ([0-9.]+) \| \*{{0,2}}\+([0-9.]+)\*{{0,2}} \|"
        m = re.search(row, _section("## The measurement", fails, "headline-auc"))
        if not m:
            fails.append(f"AUC row {per}/{who}: not found in document")
            continue
        want[(per, who)] = (
            int(m.group(1)),
            float(m.group(2)),
            float(m.group(3)),
            float(m.group(4)),
        )
    for key, (wn, wa, wse, wz) in want.items():
        a, n1, n0 = _auc(g[key[0]][key[1]])
        if a is None:
            fails.append(f"AUC {key}: no data")
            continue
        n, se = n1 + n0, _se_auc(a, n1, n0)
        if n != wn:
            fails.append(f"AUC {key}: n={n} doc says {wn}")
        if abs(a - wa) > TOL:
            fails.append(f"AUC {key}: {a:.4f} doc says {wa}")
        if abs(se - wse) > TOL:
            fails.append(f"AUC {key} SE: {se:.4f} doc says {wse}")
        z = (a - 0.5) / se
        if abs(z - wz) > 0.005:
            fails.append(f"AUC {key} z: {z:.2f} doc says {wz}")

    # --- the pooled difference-in-differences sentence ----------------------
    dm = re.search(
        r"model, MayJun - JulAug = \*{0,2}\+([0-9.]+)\*{0,2}, SE ([0-9.]+), \*{0,2}z = \+([0-9.]+)",
        text(),
    )
    if not dm:
        fails.append("DiD model sentence: not found in document")
    else:
        vals = {}
        for p_ in ("MayJun", "JulAug"):
            a, n1, n0 = _auc(g[p_]["model"])
            vals[p_] = (a, _se_auc(a, n1, n0))
        d = vals["MayJun"][0] - vals["JulAug"][0]
        sd = math.sqrt(vals["MayJun"][1] ** 2 + vals["JulAug"][1] ** 2)
        for lbl, actual, claimed, tol in (
            ("diff", d, float(dm.group(1)), TOL),
            ("SE", sd, float(dm.group(2)), TOL),
            ("z", d / sd, float(dm.group(3)), 0.005),
        ):
            if abs(actual - claimed) > tol:
                fails.append(f"DiD model {lbl}: {actual:.4f} doc says {claimed}")

    # --- monthly AUC --------------------------------------------------------
    bym = defaultdict(list)
    for m, op, _mp, y, _tk in rows:
        bym[m].append((op, float(y)))
    # "Monthly: May 0.6215 (n=51) | Jun 0.6973 (147) | Jul 0.5497 (69) | Aug 0.5085 (74)."
    months = []
    for name, mkey in (
        ("May", "2026-05"),
        ("Jun", "2026-06"),
        ("Jul", "2026-07"),
        ("Aug", "2026-08"),
    ):
        mm = re.search(rf"{name} ([0-9.]+) \(n?=?(\d+)\)", text())
        if not mm:
            fails.append(f"monthly AUC {mkey}: not found in document")
            continue
        months.append((mkey, float(mm.group(1)), int(mm.group(2))))
    for m, wa, wn in months:
        a, n1, n0 = _auc(bym[m])
        if n1 + n0 != wn:
            fails.append(f"monthly AUC {m}: n={n1 + n0} doc says {wn}")
        if a is None or abs(a - wa) > TOL:
            fails.append(f"monthly AUC {m}: {a} doc says {wa}")

    # --- forecast error table ----------------------------------------------
    with con() as c:
        fe = c.execute(
            """SELECT strftime('%Y-%m', p.predicted_at),
                      ABS(p.forecast_temp_f - o.settled_temp_f)
               FROM predictions p JOIN outcomes o ON o.ticker = p.ticker
               WHERE p.forecast_temp_f IS NOT NULL AND o.settled_temp_f IS NOT NULL
                 AND (p.ticker LIKE 'KXHIGH%' OR p.ticker LIKE 'KXLOWT%')"""
        ).fetchall()
    byfe = defaultdict(list)
    for m, e in fe:
        byfe[m].append(e)
    # Row shape: | 2026-07 | 56 | **1.18** | 2.01 | 4.14 |
    fe_want = []
    for fkey in ("2026-05", "2026-06", "2026-07", "2026-08"):
        scope = _section(
            "Raw forecast error, `|forecast_temp_f", fails, "forecast-error"
        )
        mm = re.search(
            rf"\| {fkey} \| (\d+) \| \*{{0,2}}([0-9.]+)\*{{0,2}} \| [0-9.]+ \| [0-9.]+ \|",
            scope,
        )
        if not mm:
            fails.append(f"forecast error {fkey}: row not found in document")
            continue
        fe_want.append((fkey, int(mm.group(1)), float(mm.group(2))))
    for m, wn, wmed in fe_want:
        v = byfe[m]
        if len(v) != wn:
            fails.append(f"forecast error {m}: n={len(v)} doc says {wn}")
        if v and abs(statistics.median(v) - wmed) > 0.005:
            fails.append(
                f"forecast error {m}: median {statistics.median(v):.2f} doc says {wmed}"
            )

    # --- the selection-confound table (rows with a paper trade) -------------
    import json

    pt = json.loads((DB.parent / "paper_trades.json").read_text(encoding="utf-8"))
    pt = pt if isinstance(pt, list) else pt.get("trades", pt)
    if isinstance(pt, dict):
        pt = list(pt.values())
    traded = {r["ticker"] for r in pt if r.get("ticker")}
    share: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    tg = defaultdict(list)
    for m, op, mp, y, tk in rows:
        share[m][0] += 1
        if tk in traded:
            share[m][1] += 1
            per = "MayJun" if m in ("2026-05", "2026-06") else "JulAug"
            tg[(per, "model")].append((op, float(y)))
            if mp is not None:
                tg[(per, "market")].append((mp, float(y)))
    for m, wt, wx in (
        ("2026-05", 51, 51),
        ("2026-06", 147, 147),
        ("2026-07", 69, 0),
        ("2026-08", 74, 63),
    ):
        t, x = share[m]
        if (t, x) != (wt, wx):
            fails.append(f"traded share {m}: {t}/{x} doc says {wt}/{wx}")
    tr_want = []
    for who in ("model", "market"):
        scope = _section(
            "Imposing the old regime's own selection on",
            fails,
            "traded-subset",
        )
        mm = re.search(
            rf"\| Jul-Aug \| {who} \| \*{{0,2}}(\d+)\*{{0,2}} \| \*{{0,2}}([0-9.]+)\*{{0,2}} \|",
            scope,
        )
        if not mm:
            fails.append(f"traded-subset AUC Jul-Aug/{who}: not found in document")
            continue
        tr_want.append((("JulAug", who), int(mm.group(1)), float(mm.group(2))))
    for key, wn, wa in tr_want:
        a, n1, n0 = _auc(tg[key])
        if n1 + n0 != wn:
            fails.append(f"traded-subset AUC {key}: n={n1 + n0} doc says {wn}")
        if a is None or abs(a - wa) > TOL:
            fails.append(f"traded-subset AUC {key}: {a} doc says {wa}")

    # --- n_members across the COLLAPSE WINDOW only --------------------------
    # The doc claims 238 on every July row (spanning the 06-30..07-02 step),
    # and explicitly does NOT claim constancy outside July. An earlier draft
    # did claim that and was wrong: August carries 208/258/2427/2438 too.
    with con() as c:
        jul = c.execute(
            """SELECT n_members, COUNT(*) FROM predictions
               WHERE predicted_at >= '2026-07-01' AND predicted_at < '2026-08-01'
                 AND method='ensemble' AND n_members IS NOT NULL
                 AND (ticker LIKE 'KXHIGH%' OR ticker LIKE 'KXLOWT%')
               GROUP BY n_members"""
        ).fetchall()
    if jul != [(238, 56)]:
        fails.append(f"July n_members is {jul}, doc says 238 on all 56 rows")
    # and the doc's own list of the August oddities must stay true
    with con() as c:
        aug = {
            r[0]
            for r in c.execute(
                """SELECT DISTINCT n_members FROM predictions
                   WHERE predicted_at >= '2026-08-01' AND method='ensemble'
                     AND n_members IS NOT NULL
                     AND (ticker LIKE 'KXHIGH%' OR ticker LIKE 'KXLOWT%')"""
            ).fetchall()
        }
    for odd in (2427, 2438):
        if odd not in aug:
            fails.append(f"doc cites August n_members={odd}; not present")
    return fails


def check_commits() -> list[str]:
    fails: list[str] = []
    for h, date in re.findall(
        r"`([0-9a-f]{7,8})`[^\n]*?\((\d{4}-\d{2}-\d{2})\)", text()
    ):
        r = subprocess.run(
            ["git", "log", "-1", "--format=%ad", "--date=short", h],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            fails.append(f"commit {h}: does not exist")
        elif r.stdout.strip() != date:
            fails.append(f"commit {h}: dated {r.stdout.strip()}, doc says {date}")
    return fails


# Citations where the document states what the line contains. Existence is
# not enough: an earlier draft cited tracker.py:1528 for a raw_prob assignment
# that actually lives at 1630, having copied a stale line number out of a
# source comment. The line existed, so the old gate passed.
CITATION_CONTENT = {
    ("cron.py", 2218): "_EMOS_TRAIN_GATE",
    ("ml_bias.py", 848): "def apply_temperature_scaling",
    # not cited by the document, but the entire T-scaling argument rests on
    # this being a DIVISION of the logit; if it ever becomes a multiplication
    # every inversion in the analysis silently flips.
    ("ml_bias.py", 907): "_sigmoid(_logit(prob) / T)",
    ("tracker.py", 1630): "raw_prob = round(forecast_prob + bias",
    ("weather_markets.py", 18614): "raw_prob",
}


def check_citations() -> list[str]:
    """Every `file.py:NNNN` must resolve, and named ones must CONTAIN what the
    document says they contain."""
    fails: list[str] = []
    for fname, line in re.findall(r"`?((?:[a-z_]+/)?[a-z_]+\.py):(\d{2,5})`?", text()):
        f = ROOT / fname
        if not f.exists():
            fails.append(f"{fname}:{line}: file missing")
            continue
        src = f.read_text(encoding="utf-8", errors="replace").splitlines()
        if int(line) > len(src):
            fails.append(f"{fname}:{line}: file has only {len(src)} lines")
    for (fname, ln), token in CITATION_CONTENT.items():
        f = ROOT / fname
        if not f.exists():
            fails.append(f"{fname}: missing (content check)")
            continue
        src = f.read_text(encoding="utf-8", errors="replace").splitlines()
        if ln > len(src) or token not in src[ln - 1]:
            got = src[ln - 1][:60] if ln <= len(src) else "<past EOF>"
            fails.append(f"{fname}:{ln}: expected {token!r}, line reads: {got!r}")
    return fails


# Phrases that must NOT survive, each paired with why it is stale.
STALE = [
    ("EMOS one merely has the best mechanism story", "EMOS was eliminated"),
    ("Five commits land in that window", "the window has zero commits"),
    ("split at 2026-06-27.", "the step is 06-30..07-02, not the EMOS commit"),
    ("premature_do_not_use_20260704` is still on disk", "no emos file exists"),
    ("The ratchet is real and observable", "the ratchet was retracted"),
    ("visible in the snapshots", "the ratchet was retracted"),
    ("THE LEADING HYPOTHESIS: temperature scaling", "AUC is calibration-invariant"),
    ("ratcheting T-scaling defect", "the ratchet was retracted"),
    ("now confirmed with data", "the ratchet was retracted"),
    (
        "That explains the accuracy drop",
        "compression is monotone; accuracy is invariant",
    ),
    ("So no calibration stage is degrading anything", "Finding 1 was retracted"),
    ("The model specifically broke.", "significance is not established"),
    ("**This is a REGRESSION, not a limitation.**", "significance is not established"),
]


def check_contradictions() -> list[str]:
    t = text()
    return [f"stale text present ({why}): {p!r}" for p, why in STALE if p in t]


def check_populations() -> list[str]:
    """Any n quoted for June must be reconcilable to a stated filter."""
    fails: list[str] = []
    t = text()
    if "n=48" in t.replace(" ", "") or "| 48 |" in t:
        if "blend_sources" not in t:
            fails.append("June n=48 and n=44 both appear but no filter is stated")
    return fails


def check_rederive() -> list[str]:
    """Execute the document's own re-derivation recipe literally."""
    fails: list[str] = []
    with con() as c:
        rows = c.execute(
            """SELECT strftime('%Y-%m', p.predicted_at), p.our_prob, p.raw_prob
               FROM predictions p JOIN outcomes_valid o ON o.ticker = p.ticker
               WHERE o.settled_yes IN (0,1) AND p.our_prob IS NOT NULL
                 AND p.method='ensemble'
                 AND (p.ticker LIKE 'KXHIGH%' OR p.ticker LIKE 'KXLOWT%')"""
        ).fetchall()
    by = defaultdict(list)
    for m, op, rp in rows:
        by[m].append((op, rp))
    # Row shape: | 2026-06 | 48 | 0.1958 | 0.1958 | 37.5% |
    rd_want = []
    for key in ("2026-05", "2026-06", "2026-07", "2026-08"):
        scope = _section(
            "## Superseded: the original Finding 1 numbers", fails, "rederive"
        )
        mm = re.search(
            rf"\| {key} \| (\d+) \| ([0-9.]+) \| ([0-9.]+) \| [0-9.]+% \|", scope
        )
        if not mm:
            fails.append(f"rederive {key}: row not found in document")
            continue
        rd_want.append((key, int(mm.group(1)), float(mm.group(2))))
    for m, wn, wconf in rd_want:
        v = by[m]
        if len(v) != wn:
            fails.append(f"rederive {m}: recipe yields n={len(v)}, doc says {wn}")
            continue
        conf = statistics.fmean(abs(p - 0.5) for p, _ in v)
        if abs(conf - wconf) > TOL:
            fails.append(f"rederive {m}: conf {conf:.4f}, doc says {wconf}")
    return fails


def check_strata() -> list[str]:
    """Gate the stratified-AUC table, the composition table, and every z.

    Added after a mutation-based coverage sweep on 2026-08-30 found 267 of 310
    numeric claims ungated (13.9% covered) -- including every z-value and the
    entirety of both tables added by the preceding hardening pass. A finding
    added without a gate is a finding the ledger will certify wrong.
    """
    fails: list[str] = []
    rows = _core_rows_ct()

    def per(m):
        return "MayJun" if m in ("2026-05", "2026-06") else "JulAug"

    # --- composition table --------------------------------------------------
    tot: dict[str, int] = defaultdict(int)
    cnt: dict[tuple, int] = defaultdict(int)
    for m, _op, _mp, _y, ct, _tk in rows:
        tot[per(m)] += 1
        cnt[(per(m), ct)] += 1
    scope = _section(
        "| condition | May-Jun share | Jul-Aug share |", fails, "composition"
    )
    for ct in ("between", "above", "below"):
        mm = re.search(
            rf"\| `{ct}` \| \*{{0,2}}([0-9.]+)%\*{{0,2}} \| \*{{0,2}}([0-9.]+)%\*{{0,2}} \|",
            scope,
        )
        if not mm:
            fails.append(f"composition row {ct}: not found in document")
            continue
        for i, p_ in enumerate(("MayJun", "JulAug")):
            claimed = float(mm.group(i + 1))
            actual = 100 * cnt[(p_, ct)] / tot[p_]
            if abs(actual - claimed) > 0.05:
                fails.append(
                    f"composition {ct}/{p_}: {actual:.1f}% doc says {claimed}%"
                )

    # --- stratified AUC table, including z ---------------------------------
    g: dict[tuple, list] = defaultdict(list)
    for m, op, mp, y, ct, _tk in rows:
        g[(per(m), ct, "model")].append((op, float(y)))
        if mp is not None:
            g[(per(m), ct, "market")].append((mp, float(y)))
    sc = _section(
        "| condition | period | who | n | AUC | SE | z vs 0.50 |", fails, "strata"
    )
    for ct, lbl, who in (
        ("above", "May-Jun", "model"),
        ("above", "Jul-Aug", "model"),
        ("below", "May-Jun", "model"),
        ("below", "Jul-Aug", "model"),
        ("between", "May-Jun", "model"),
    ):
        mm = re.search(
            rf"\| {ct} \| {lbl} \| {who} \| (\d+) \| \*{{0,2}}([0-9.]+)\*{{0,2}} \| ([0-9.]+) \| \*{{0,2}}([+-][0-9.]+)\*{{0,2}} \|",
            sc,
        )
        if not mm:
            fails.append(f"strata row {ct}/{lbl}: not found in document")
            continue
        p_ = "MayJun" if lbl == "May-Jun" else "JulAug"
        a, n1, n0 = _auc(g[(p_, ct, who)])
        if a is None:
            fails.append(f"strata {ct}/{lbl}: no data")
            continue
        se = _se_auc(a, n1, n0)
        z = (a - 0.5) / se
        for label, actual, claimed, tol in (
            ("n", n1 + n0, int(mm.group(1)), 0),
            ("AUC", a, float(mm.group(2)), TOL),
            ("SE", se, float(mm.group(3)), TOL),
            ("z", z, float(mm.group(4)), 0.005),
        ):
            if abs(actual - claimed) > tol:
                fails.append(f"strata {ct}/{lbl} {label}: {actual} doc says {claimed}")

    # --- pooled AUC sentence, with its z ------------------------------------
    mm = re.search(
        r"Pooled model AUC ([0-9.]+) \(n=(\d+), z=\+([0-9.]+)\); pooled market ([0-9.]+) \(z=\+([0-9.]+)\)",
        text(),
    )
    if not mm:
        fails.append("pooled AUC sentence: not found in document")
    else:
        allm = [(op, float(y)) for _m, op, _mp, y, _ct, _tk in rows]
        allk = [(mp, float(y)) for _m, _op, mp, y, _ct, _tk in rows if mp is not None]
        for lbl, pairs, wa, wz in (
            ("model", allm, float(mm.group(1)), float(mm.group(3))),
            ("market", allk, float(mm.group(4)), float(mm.group(5))),
        ):
            a, n1, n0 = _auc(pairs)
            z = (a - 0.5) / _se_auc(a, n1, n0)
            if abs(a - wa) > TOL:
                fails.append(f"pooled {lbl} AUC: {a:.4f} doc says {wa}")
            if abs(z - wz) > 0.005:
                fails.append(f"pooled {lbl} z: {z:.2f} doc says {wz}")
        if int(mm.group(2)) != len(allm):
            fails.append(f"pooled n: {len(allm)} doc says {mm.group(2)}")
    return fails


def _core_rows_ct():
    with con() as c:
        return c.execute(
            """SELECT strftime('%Y-%m', p.predicted_at), p.our_prob, p.market_prob,
                      o.settled_yes, p.condition_type, p.ticker
               FROM predictions p JOIN outcomes_valid o ON o.ticker = p.ticker
               WHERE o.settled_yes IN (0,1) AND p.our_prob IS NOT NULL
                 AND (p.ticker LIKE 'KXHIGH%' OR p.ticker LIKE 'KXLOWT%')"""
        ).fetchall()


def check_restatements() -> list[str]:
    """Prose that restates a gated figure must agree with it.

    A mutation-coverage sweep on 2026-08-30 showed that figures repeated in
    prose (e.g. "the model fell to chance (0.5321, z=+0.66)") were UNGATED
    even though the same numbers were gated inside their table. Editing only
    the prose would leave the ledger green while the document contradicted
    itself. This gate ties each restatement back to a freshly derived value.
    """
    fails: list[str] = []
    rows = _core_rows_ct()

    def per(m):
        return "MayJun" if m in ("2026-05", "2026-06") else "JulAug"

    g: dict[tuple, list] = defaultdict(list)
    for m, op, mp, y, ct, _tk in rows:
        g[(per(m), "model")].append((op, float(y)))
        if mp is not None:
            g[(per(m), "market")].append((mp, float(y)))

    derived = {}
    for p_ in ("MayJun", "JulAug"):
        for who in ("model", "market"):
            a, n1, n0 = _auc(g[(p_, who)])
            derived[(p_, who)] = (a, (a - 0.5) / _se_auc(a, n1, n0))

    # RETIRED 2026-08-30: the five prose restatements of the headline
    # table were cut in the 212-line condensation. Recorded in
    # GATES-handoff-audit.md rather than silently dropped.

    # family drift percentages
    fm = re.search(
        r"KXHIGH ([0-9.]+)% -> ([0-9.]+)%, KXLOWT ([0-9.]+)% -> ([0-9.]+)%", text()
    )
    if not fm:
        fails.append("family drift sentence: not found in document")
    else:
        tot: dict[str, int] = defaultdict(int)
        cnt: dict[tuple, int] = defaultdict(int)
        for m, _op, _mp, _y, _ct, tk in rows:
            fam = "KXLOWT" if tk.startswith("KXLOWT") else "KXHIGH"
            tot[per(m)] += 1
            cnt[(per(m), fam)] += 1
        for i, (fam, p_) in enumerate(
            [
                ("KXHIGH", "MayJun"),
                ("KXHIGH", "JulAug"),
                ("KXLOWT", "MayJun"),
                ("KXLOWT", "JulAug"),
            ]
        ):
            actual = 100 * cnt[(p_, fam)] / tot[p_]
            claimed = float(fm.group(i + 1))
            if abs(actual - claimed) > 0.05:
                fails.append(f"family {fam}/{p_}: {actual:.1f}% doc says {claimed}%")
    return fails


def check_market_strata() -> list[str]:
    """Gate the market's per-stratum AUCs and the live temperature_scale values.

    Both were GENUINE ungated claims in the 2026-08-30 coverage sweep. The
    market stratum figures carry the document's "what survives composition"
    argument; the T values carry the self-training-loop section. Neither had
    any oracle.
    """
    fails: list[str] = []
    rows = _core_rows_ct()

    def per(m):
        return "MayJun" if m in ("2026-05", "2026-06") else "JulAug"

    g: dict[tuple, list] = defaultdict(list)
    for m, _op, mp, y, ct, _tk in rows:
        if mp is not None:
            g[(per(m), ct)].append((mp, float(y)))

    mm = re.search(
        r"`above` ([0-9.]+)\s*->\s*([0-9.]+), `below` ([0-9.]+) -> ([0-9.]+)", text()
    )
    if not mm:
        fails.append("market stratum sentence: not found in document")
    else:
        for i, (ct, p_) in enumerate(
            [
                ("above", "MayJun"),
                ("above", "JulAug"),
                ("below", "MayJun"),
                ("below", "JulAug"),
            ]
        ):
            a, n1, n0 = _auc(g[(p_, ct)])
            claimed = float(mm.group(i + 1))
            if a is None or abs(a - claimed) > TOL:
                fails.append(f"market {ct}/{p_} AUC: {a} doc says {claimed}")

    # live temperature_scale.json, quoted in the self-training section
    import json

    ts = json.loads((DB.parent / "temperature_scale.json").read_text(encoding="utf-8"))
    tm = re.search(
        r"`sameday` \*\*T = ([0-9.]+)\*\* \(n=(\d+)\).{0,40}`global`\s+T = ([0-9.]+) \(n=(\d+)\), `above` T = ([0-9.]+) \(n=(\d+)\)",
        text(),
        re.S,
    )
    if not tm:
        fails.append("temperature_scale sentence: not found in document")
    else:
        for i, key in enumerate(("sameday", "global", "above")):
            wt, wn = float(tm.group(2 * i + 1)), int(tm.group(2 * i + 2))
            got = ts.get(key, {})
            if abs(float(got.get("T", -1)) - wt) > 1e-4:
                fails.append(f"temperature_scale {key} T: {got.get('T')} doc says {wt}")
            if int(got.get("n", -1)) != wn:
                fails.append(f"temperature_scale {key} n: {got.get('n')} doc says {wn}")
    return fails


CHECKS = {
    "--numbers": ("HANDOFF_NUMBERS_OK", check_numbers),
    "--commits": ("HANDOFF_COMMITS_OK", check_commits),
    "--citations": ("HANDOFF_CITATIONS_OK", check_citations),
    "--contradictions": ("HANDOFF_NO_CONTRADICTIONS", check_contradictions),
    "--populations": ("HANDOFF_POPULATIONS_OK", check_populations),
    "--strata": ("HANDOFF_STRATA_OK", check_strata),
    "--restatements": ("HANDOFF_RESTATEMENTS_OK", check_restatements),
    "--market-strata": ("HANDOFF_MARKET_STRATA_OK", check_market_strata),
}


def _load_extensions() -> None:
    """Register the extended gates.

    Imported inside main() rather than at module scope: running this file as a
    script makes it __main__, so a module-level import of the sibling would
    re-import this file under its real name and hit a half-initialised module,
    printing a spurious warning while everything actually worked.
    """
    from audit_handoff_ext import EXT_CHECKS
    from audit_handoff_prose import PROSE_CHECKS
    from audit_handoff_prose2 import PROSE2_CHECKS
    from audit_handoff_singletons import SINGLETON_CHECKS

    CHECKS.update(EXT_CHECKS)
    CHECKS.update(PROSE_CHECKS)
    CHECKS.update(PROSE2_CHECKS)
    CHECKS.update(SINGLETON_CHECKS)


def main() -> int:
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    _load_extensions()
    args = sys.argv[1:] or ["--all"]
    todo = list(CHECKS) if args == ["--all"] else args
    bad = 0
    for a in todo:
        if a not in CHECKS:
            print(f"unknown check {a}")
            return 2
        token, fn = CHECKS[a]
        try:
            fails = fn()
        except Exception as exc:  # a broken check is a failure, not a pass
            print(f"{a}: RAISED {type(exc).__name__}: {exc}")
            bad += 1
            continue
        if fails:
            bad += 1
            print(f"{a}: {len(fails)} FAILURE(S)")
            for f in fails:
                print(f"    - {f}")
        else:
            print(f"{a}: {token}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
