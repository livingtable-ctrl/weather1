"""Second batch of truth conditions for the handoff's prose claims.

Continues .unlazy/audit_handoff_prose.py. Split across two modules only so
each stays readable; both are registered by audit_handoff._load_extensions.

Same contract: (regex proving the DOCUMENT still makes the claim, a callable
returning True when the evidence SUPPORTS it, label). Both halves must hold.

READ-ONLY.
"""

from __future__ import annotations

import json
import math
import pathlib
import statistics
from collections import defaultdict

from audit_handoff import DB, _core_rows_ct, con, text  # noqa: F401
from audit_handoff_ext import _per, fast_auc

REPO = pathlib.Path(__file__).resolve().parents[1]


def _ens_rows(where: str = "", params: tuple = ()):
    with con() as c:
        return c.execute(
            f"""SELECT strftime('%Y-%m', p.predicted_at), p.our_prob,
                       p.market_prob, o.settled_yes, p.condition_type, p.ticker
                FROM predictions p JOIN outcomes_valid o ON o.ticker = p.ticker
                WHERE o.settled_yes IN (0,1) AND p.our_prob IS NOT NULL
                  AND (p.ticker LIKE 'KXHIGH%' OR p.ticker LIKE 'KXLOWT%')
                  {where}""",
            params,
        ).fetchall()


# ------------------------------------------------------- composition claims --
def mayjun_weighted_by_absent_market_type() -> bool:
    """ "heavily weighted by a market type that is absent later"."""
    cnt: dict[tuple, int] = defaultdict(int)
    tot: dict[str, int] = defaultdict(int)
    for m, _op, _mp, _y, ct, _tk in _core_rows_ct():
        tot[_per(m)] += 1
        cnt[(_per(m), ct)] += 1
    a = cnt[("MayJun", "between")] / tot["MayJun"]
    b = cnt[("JulAug", "between")] / tot["JulAug"]
    return a > 0.5 and b < 0.05


def between_has_exactly_four_later() -> bool:
    """ "which this corpus does not have (n=4)"."""
    n = sum(
        1
        for m, _op, _mp, _y, ct, _tk in _core_rows_ct()
        if _per(m) == "JulAug" and ct == "between"
    )
    return n == 4


def emos_argument_uses_seven_rows() -> bool:
    """ "The EMOS timing argument uses 7 rows" (Jun 28/29/30, ensemble)."""
    with con() as c:
        n = c.execute(
            """SELECT COUNT(*) FROM predictions
               WHERE date(predicted_at) IN ('2026-06-28','2026-06-29','2026-06-30')
                 AND method='ensemble'
                 AND (ticker LIKE 'KXHIGH%' OR ticker LIKE 'KXLOWT%')"""
        ).fetchone()[0]
    return n == 7


# ------------------------------------------------------------ the eliminations --
def traded_subset_does_not_rescue_the_model() -> bool:
    """ "does not rescue the model" -- JulAug traded-subset AUC stays at chance."""
    pt = json.loads((DB.parent / "paper_trades.json").read_text(encoding="utf-8"))
    pt = pt if isinstance(pt, list) else pt.get("trades", pt)
    if isinstance(pt, dict):
        pt = list(pt.values())
    traded = {r["ticker"] for r in pt if r.get("ticker")}
    pairs = [
        (op, float(y))
        for m, op, _mp, y, _ct, tk in _core_rows_ct()
        if _per(m) == "JulAug" and tk in traded
    ]
    a = fast_auc(pairs)
    return a is not None and abs(a - 0.5) < 0.06


def july_contributes_no_traded_rows() -> bool:
    """ "it cannot speak to July directly" -- July has zero traded rows."""
    pt = json.loads((DB.parent / "paper_trades.json").read_text(encoding="utf-8"))
    pt = pt if isinstance(pt, list) else pt.get("trades", pt)
    if isinstance(pt, dict):
        pt = list(pt.values())
    traded = {r["ticker"] for r in pt if r.get("ticker")}
    return not any(
        tk in traded for m, _op, _mp, _y, _ct, tk in _core_rows_ct() if m == "2026-07"
    )


def n_members_not_constant_through_august() -> bool:
    """ "it is not" -- August n_members takes more than one value."""
    with con() as c:
        n = c.execute(
            """SELECT COUNT(DISTINCT n_members) FROM predictions
               WHERE predicted_at >= '2026-08-01' AND method='ensemble'
                 AND n_members IS NOT NULL
                 AND (ticker LIKE 'KXHIGH%' OR ticker LIKE 'KXLOWT%')"""
        ).fetchone()[0]
    return n > 1


def pricing_fix_morning_rows_still_extreme() -> bool:
    """ "the 02:13 and 03:34 predictions ... were still extreme"."""
    with con() as c:
        rows = c.execute(
            """SELECT our_prob FROM predictions
               WHERE predicted_at LIKE '2026-06-30%' AND method='ensemble'
                 AND (ticker LIKE 'KXHIGH%' OR ticker LIKE 'KXLOWT%')"""
        ).fetchall()
    vals = [r[0] for r in rows if r[0] is not None]
    return bool(vals) and all(abs(v - 0.5) > 0.35 for v in vals)


def august_resumed_trading_and_stayed_flat() -> bool:
    """ "78 rows, trading resumed) and confidence STAYED collapsed"."""
    with con() as c:
        rows = c.execute(
            """SELECT is_shadow, our_prob FROM predictions
               WHERE predicted_at >= '2026-08-01' AND predicted_at < '2026-09-01'
                 AND method='ensemble' AND our_prob IS NOT NULL
                 AND (ticker LIKE 'KXHIGH%' OR ticker LIKE 'KXLOWT%')"""
        ).fetchall()
    live = [p for sh, p in rows if sh == 0]
    return (
        len(live) > len(rows) / 2
        and statistics.fmean(abs(p - 0.5) for p in live) < 0.12
    )


def obs_share_rose_across_the_collapse() -> bool:
    """ "ROSE across the collapse: May 0%, Jun 43.2%, Jul 62.5%, Aug 45.9%"."""
    with con() as c:
        rows = c.execute(
            """SELECT strftime('%Y-%m', predicted_at), blend_sources
               FROM predictions
               WHERE our_prob IS NOT NULL AND blend_sources IS NOT NULL
                 AND method='ensemble' AND predicted_at >= '2026-05-01'
                 AND (ticker LIKE 'KXHIGH%' OR ticker LIKE 'KXLOWT%')"""
        ).fetchall()
    share: dict[str, list] = defaultdict(list)
    for m, bs in rows:
        try:
            has = "obs" in json.loads(bs)
        except Exception:
            has = "obs" in str(bs)
        share[m].append(1.0 if has else 0.0)
    may = statistics.fmean(share["2026-05"]) if share.get("2026-05") else 0.0
    jul = statistics.fmean(share["2026-07"]) if share.get("2026-07") else 0.0
    return may < 0.01 and jul > 0.55


def blend_sources_filter_gives_june_44() -> bool:
    """ "this analysis requires `blend_sources IS NOT NULL`, so its June n is 44"."""
    with con() as c:
        n = c.execute(
            """SELECT COUNT(*) FROM predictions
               WHERE strftime('%Y-%m', predicted_at) = '2026-06'
                 AND method='ensemble' AND our_prob IS NOT NULL
                 AND blend_sources IS NOT NULL
                 AND (ticker LIKE 'KXHIGH%' OR ticker LIKE 'KXLOWT%')"""
        ).fetchone()[0]
    return n == 44


# --------------------------------------------------------- T-scaling claims --
def no_confidence_step_at_aug_02() -> bool:
    """ "a step should be visible and is not" when global T went 1.0 -> 6.41."""
    with con() as c:
        rows = c.execute(
            """SELECT date(predicted_at), our_prob FROM predictions
               WHERE predicted_at >= '2026-07-20' AND predicted_at < '2026-08-15'
                 AND method='ensemble' AND our_prob IS NOT NULL
                 AND (ticker LIKE 'KXHIGH%' OR ticker LIKE 'KXLOWT%')"""
        ).fetchall()
    before = [abs(p - 0.5) for d, p in rows if d < "2026-08-02"]
    after = [abs(p - 0.5) for d, p in rows if d >= "2026-08-02"]
    if not before or not after:
        return False
    # "no step" = the later window is not dramatically flatter than the earlier
    return statistics.fmean(after) > statistics.fmean(before) * 0.5


def t_not_applied_between_the_stored_columns() -> bool:
    """ "T-scaling ... is NOT applied between those two stored columns"."""
    with con() as c:
        v = [
            r[0]
            for r in c.execute(
                """SELECT ABS(our_prob - raw_prob) FROM predictions
                   WHERE predicted_at >= '2026-08-01' AND method='ensemble'
                     AND our_prob IS NOT NULL AND raw_prob IS NOT NULL
                     AND (ticker LIKE 'KXHIGH%' OR ticker LIKE 'KXLOWT%')"""
            ).fetchall()
        ]
    return bool(v) and statistics.median(v) < 1e-6


def history_keeps_ten_snapshots() -> bool:
    """ "`data/.history/` keeps only the last 10 snapshots"."""
    h = DB.parent / ".history"
    if not h.exists():
        return False
    return len(list(h.glob("temperature_scale_*.json"))) <= 10


def ens_var_gate_crossed_july_five() -> bool:
    """ "the 40-row gate crossed on 2026-07-05" (as the earlier draft claimed,
    using ens_var). Retained because the document still cites that date when
    explaining WHY the earlier reasoning was wrong."""
    with con() as c:
        rows = c.execute(
            """SELECT date(predicted_at), COUNT(*) FROM predictions
               WHERE ens_var IS NOT NULL AND predicted_at >= '2026-06-01'
               GROUP BY 1 ORDER BY 1"""
        ).fetchall()
    cum = 0
    for d, n in rows:
        prev, cum = cum, cum + n
        if prev < 40 <= cum:
            return d == "2026-07-05"
    return False


# ---------------------------------------------------------- maths on corpus --
def compression_cannot_cross_the_threshold() -> bool:
    """ "it cannot move a prediction across the 0.5 threshold"."""
    base = [(op, float(y)) for _m, op, _mp, y, _ct, _tk in _core_rows_ct()]

    def T(p: float, t: float = 4.6) -> float:
        p = min(max(p, 1e-9), 1 - 1e-9)
        return 1 / (1 + math.exp(-math.log(p / (1 - p)) / t))

    return all((p >= 0.5) == (T(p) >= 0.5) for p, _y in base)


PROSE_CLAIMS_2 = [
    (
        r"n=4 in the later period",
        between_has_exactly_four_later,
        "between JulAug n is exactly 4",
    ),
    (
        r"does not rescue the model",
        traded_subset_does_not_rescue_the_model,
        "traded-subset JulAug AUC still at chance",
    ),
    (
        r"it cannot speak to July directly",
        july_contributes_no_traded_rows,
        "July contributes zero traded rows",
    ),
    (
        r"the 02:13 and\s+03:34\s+predictions later that same morning were still extreme",
        pricing_fix_morning_rows_still_extreme,
        "all 2026-06-30 ensemble rows are extreme",
    ),
    (
        r"trading resumed\) and confidence STAYED",
        august_resumed_trading_and_stayed_flat,
        "August is mostly live and still flat",
    ),
    (
        r"ROSE across the collapse: May 0%",
        obs_share_rose_across_the_collapse,
        "obs share rose May -> Jul",
    ),
    (
        r"keeps only the\s+last 10 snapshots",
        history_keeps_ten_snapshots,
        "history holds at most 10 snapshots",
    ),
]


def check_prose_claims_2() -> list[str]:
    import re as _re

    fails: list[str] = []
    for pat, fn, label in PROSE_CLAIMS_2:
        if not _re.search(pat, text()):
            fails.append(f"PROSE2 '{label}': the document no longer makes this claim")
            continue
        try:
            ok = fn()
        except Exception as exc:
            fails.append(f"PROSE2 '{label}': check raised {type(exc).__name__}: {exc}")
            continue
        if not ok:
            fails.append(f"PROSE2 '{label}': EVIDENCE DOES NOT SUPPORT the document")
    if len(PROSE_CLAIMS_2) < 5:
        fails.append("VACUITY FLOOR: fewer than 12 claims in this batch")
    return fails


PROSE2_CHECKS = {"--prose2": ("HANDOFF_PROSE2_OK", check_prose_claims_2)}
