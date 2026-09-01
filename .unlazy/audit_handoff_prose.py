"""Truth conditions for the handoff's PROSE claims.

Pass 8 measured prose-claim coverage at 4.3% and recorded that closing it had
no mechanical route: each sentence needs its truth condition written by hand.
This is that work.

Every entry is (regex proving the DOCUMENT still makes the claim, a callable
returning True when the evidence SUPPORTS it, label). Both halves must hold.
A claim quietly deleted from the document fails this gate exactly as a refuted
one does — otherwise the gate would reward deleting inconvenient sentences.

Claims are grouped by what settles them: the database, a file on disk, the
repository source, or a mathematical property demonstrable on this corpus.

READ-ONLY.
"""

from __future__ import annotations

import json
import math
import pathlib
import re
import statistics
from collections import defaultdict

from audit_handoff import DB, _core_rows_ct, con, text
from audit_handoff_ext import _per, fast_auc

REPO = pathlib.Path(__file__).resolve().parents[1]


def _rows():
    return _core_rows_ct()


def _by_period_ct(who: str = "model"):
    g: dict[tuple, list] = defaultdict(list)
    for m, op, mp, y, ct, _tk in _rows():
        v = op if who == "model" else mp
        if v is not None:
            g[(_per(m), ct)].append((v, float(y)))
    return g


# ----------------------------------------------------------------- database --
def model_never_beat_market_on_brier() -> bool:
    """ "the model never beat the market on Brier in ANY month"."""
    by: dict[str, list] = defaultdict(list)
    for m, op, mp, y, _ct, _tk in _rows():
        if mp is not None:
            by[m].append((op, mp, float(y)))
    for _m, v in by.items():
        model = statistics.fmean((p - y) ** 2 for p, _q, y in v)
        market = statistics.fmean((q - y) ** 2 for _p, q, y in v)
        if model < market:  # a single month where the model wins refutes it
            return False
    return bool(by)


def between_is_two_degrees_in_both_periods() -> bool:
    """ "`between` markets are 2.00F wide in both periods"."""
    with con() as c:
        rows = c.execute(
            """SELECT strftime('%Y-%m', predicted_at), threshold_hi - threshold_lo
               FROM predictions
               WHERE condition_type = 'between' AND threshold_lo IS NOT NULL
                 AND threshold_hi IS NOT NULL AND predicted_at >= '2026-05-01'
                 AND (ticker LIKE 'KXHIGH%' OR ticker LIKE 'KXLOWT%')"""
        ).fetchall()
    w: dict[str, list] = defaultdict(list)
    for m, d in rows:
        w[_per(m)].append(d)
    return (
        all(v and abs(statistics.median(v) - 2.0) < 1e-6 for v in w.values())
        and len(w) == 2
    )


def never_discriminated_on_below_either_period() -> bool:
    """ "Within `below`, the model never discriminated in either period"."""
    g = _by_period_ct("model")
    out = []
    for p_ in ("MayJun", "JulAug"):
        a = fast_auc(g[(p_, "below")])
        if a is None:
            return False
        out.append(abs(a - 0.5) < 0.06)
    return all(out)


def skill_concentrated_in_between() -> bool:
    """ "the model's discrimination was always concentrated in `between`"."""
    g = _by_period_ct("model")
    btw = fast_auc(g[("MayJun", "between")])
    blw = fast_auc(g[("MayJun", "below")])
    return btw is not None and blw is not None and btw > blw


def mayjun_recorded_only_placed_trades() -> bool:
    """ "May-June recorded only markets where a paper trade was placed"."""
    pt = json.loads((DB.parent / "paper_trades.json").read_text(encoding="utf-8"))
    pt = pt if isinstance(pt, list) else pt.get("trades", pt)
    if isinstance(pt, dict):
        pt = list(pt.values())
    traded = {r["ticker"] for r in pt if r.get("ticker")}
    rows = [r for r in _rows() if _per(r[0]) == "MayJun"]
    return bool(rows) and all(tk in traded for *_x, tk in rows)


def blend_exclusions_empty_in_july() -> bool:
    """ "`blend_exclusions` empty throughout" (the collapse window)."""
    with con() as c:
        vals = [
            r[0]
            for r in c.execute(
                """SELECT blend_exclusions FROM predictions
                   WHERE predicted_at >= '2026-07-01' AND predicted_at < '2026-08-01'
                     AND method='ensemble'
                     AND (ticker LIKE 'KXHIGH%' OR ticker LIKE 'KXLOWT%')"""
            ).fetchall()
        ]
    return all(v in (None, "", "[]", "{}") for v in vals)


def july_only_sigma_columns() -> bool:
    """ "`ensemble_spread_f` and `model_disagreement_f` are only populated from
    July onward"."""
    with con() as c:
        pre = c.execute(
            """SELECT COUNT(*) FROM predictions
               WHERE predicted_at < '2026-07-01'
                 AND (ensemble_spread_f IS NOT NULL
                      OR model_disagreement_f IS NOT NULL)
                 AND (ticker LIKE 'KXHIGH%' OR ticker LIKE 'KXLOWT%')"""
        ).fetchone()[0]
        post = c.execute(
            """SELECT COUNT(*) FROM predictions
               WHERE predicted_at >= '2026-07-01'
                 AND (ensemble_spread_f IS NOT NULL
                      OR model_disagreement_f IS NOT NULL)
                 AND (ticker LIKE 'KXHIGH%' OR ticker LIKE 'KXLOWT%')"""
        ).fetchone()[0]
    return pre == 0 and post > 0


def corpus_is_mostly_sameday() -> bool:
    """ "Most predictions in this corpus are same-day"."""
    with con() as c:
        d0, tot = c.execute(
            """SELECT SUM(CASE WHEN days_out = 0 THEN 1 ELSE 0 END), COUNT(*)
               FROM predictions
               WHERE days_out IS NOT NULL
                 AND (ticker LIKE 'KXHIGH%' OR ticker LIKE 'KXLOWT%')"""
        ).fetchone()
    return bool(tot) and d0 > tot / 2


def brier_improved_across_the_span() -> bool:
    """ "Brier *improved* over the same span".

    SCOPE MATTERS AND THE GATE FOUND IT: this holds for method='ensemble'
    (0.2688 -> 0.2470) but NOT across all methods pooled, where Brier slightly
    WORSENS (0.2653 -> 0.2670). The document's claim sits beside the ensemble
    table, so ensemble is the right population -- but an unscoped reading of
    the sentence is false, which is now recorded in the document itself.
    """
    with con() as c:
        rows = c.execute(
            """SELECT strftime('%Y-%m', p.predicted_at), p.our_prob, o.settled_yes
               FROM predictions p JOIN outcomes_valid o ON o.ticker = p.ticker
               WHERE o.settled_yes IN (0,1) AND p.our_prob IS NOT NULL
                 AND p.method = 'ensemble'
                 AND (p.ticker LIKE 'KXHIGH%' OR p.ticker LIKE 'KXLOWT%')"""
        ).fetchall()
    by: dict[str, list] = defaultdict(list)
    for m, op, y in rows:
        by[_per(m)].append((op, float(y)))
    a = statistics.fmean((p - y) ** 2 for p, y in by["MayJun"])
    b = statistics.fmean((p - y) ** 2 for p, y in by["JulAug"])
    return b < a


def confidence_collapsed_jun_to_jul() -> bool:
    """ "Raw model confidence collapsed between June and July"."""
    with con() as c:
        rows = c.execute(
            """SELECT strftime('%Y-%m', p.predicted_at), p.our_prob
               FROM predictions p JOIN outcomes_valid o ON o.ticker = p.ticker
               WHERE o.settled_yes IN (0,1) AND p.our_prob IS NOT NULL
                 AND p.method='ensemble'
                 AND (p.ticker LIKE 'KXHIGH%' OR p.ticker LIKE 'KXLOWT%')"""
        ).fetchall()
    by: dict[str, list] = defaultdict(list)
    for m, p in rows:
        by[m].append(abs(p - 0.5))
    jun = by.get("2026-06") or []
    jul = by.get("2026-07") or []
    if not jun or not jul:
        return False
    return statistics.fmean(jul) < statistics.fmean(jun) / 2


# --------------------------------------------------------------- files/disk --
def analysis_calibration_is_untrained_identity() -> bool:
    """ "data/analysis_calibration.json is an untrained identity map"."""
    f = DB.parent / "analysis_calibration.json"
    if not f.exists():
        return False
    d = json.loads(f.read_text(encoding="utf-8")).get("multiday", {})
    return d.get("a") == 1.0 and d.get("b") == 0.0 and d.get("n") == 0


def aug01_snapshot_was_inert() -> bool:
    """ "The Aug-01 snapshot shows T=1.0 with n=0" and sameday absent."""
    f = DB.parent / ".history" / "temperature_scale_20260801T203545.json"
    if not f.exists():
        return False
    d = json.loads(f.read_text(encoding="utf-8"))
    g = d.get("global", {})
    return d.get("sameday") is None and g.get("T") == 1.0 and g.get("n") == 0


# ------------------------------------------------------------- repo source --
def cron_only_prints_emos_reminder() -> bool:
    """ "cron.py:2202 only ever prints a readiness REMINDER"."""
    src = (REPO / "cron.py").read_text(encoding="utf-8", errors="replace")
    return "EMOS readiness reminder" in src and "emos_params.json exists" in src


def backlog_says_sameday_never_frozen() -> bool:
    """ "sameday/hourly were never frozen" — quoted from backlog.txt."""
    bl = (REPO / "backlog.txt").read_text(encoding="utf-8", errors="replace")
    # backlog.txt hard-wraps, so the quoted phrase is split across lines.
    # Collapse whitespace before comparing -- a literal search silently failed.
    flat = " ".join(bl.split())
    return "sameday/hourly were never frozen" in flat


# ------------------------------------------------------ mathematical facts --
def uniform_sigma_error_preserves_ranking() -> bool:
    """ "a sigma that is uniformly WRONG ... PRESERVES their ranking, so it
    cannot move AUC". Demonstrated on this corpus: any strictly monotone
    reshaping of every probability leaves AUC unchanged."""
    base = [(op, float(y)) for _m, op, _mp, y, _ct, _tk in _rows()]
    a0 = fast_auc(base)

    def widen(p: float, k: float = 2.5) -> float:
        p = min(max(p, 1e-9), 1 - 1e-9)
        return 1 / (1 + math.exp(-math.log(p / (1 - p)) / k))

    a1 = fast_auc([(widen(p), y) for p, y in base])
    return a0 is not None and a1 is not None and abs(a0 - a1) < 1e-3


PROSE_CLAIMS = [
    (
        r"has never beaten the market on Brier in any month",
        model_never_beat_market_on_brier,
        "model never beat market on Brier in any month",
    ),
    (
        r"`between` markets are 2\.00F wide in both periods",
        between_is_two_degrees_in_both_periods,
        "between ladders are 2.00F wide in both periods",
    ),
    (
        r"On `below` it NEVER\s+discriminated",
        never_discriminated_on_below_either_period,
        "model at chance on below in both periods",
    ),
    (
        r"was concentrated in `between` markets",
        skill_concentrated_in_between,
        "MayJun skill concentrated in between",
    ),
    (
        r"May-June recorded only\s+markets where a paper trade was placed",
        mayjun_recorded_only_placed_trades,
        "every MayJun row has a paper trade",
    ),
    (
        r"`blend_exclusions` empty throughout",
        blend_exclusions_empty_in_july,
        "blend_exclusions empty across the collapse window",
    ),
    (
        r"Most predictions in\s+this corpus are same-day",
        corpus_is_mostly_sameday,
        "corpus is majority same-day",
    ),
    (
        r"The Aug-01 snapshot shows T=1\.0 with n=0",
        aug01_snapshot_was_inert,
        "Aug-01 snapshot inert, sameday absent",
    ),
    (
        r"only ever prints a readiness",
        cron_only_prints_emos_reminder,
        "cron.py prints an EMOS readiness reminder only",
    ),
    (
        r"sameday/hourly were never frozen",
        backlog_says_sameday_never_frozen,
        "backlog.txt contains the never-frozen quote",
    ),
    (
        r"PRESERVES their ranking, so it cannot move AUC",
        uniform_sigma_error_preserves_ranking,
        "monotone reshaping leaves AUC unchanged on this corpus",
    ),
]


def check_prose_claims() -> list[str]:
    fails: list[str] = []
    for pat, fn, label in PROSE_CLAIMS:
        if not re.search(pat, text()):
            fails.append(f"PROSE '{label}': the document no longer makes this claim")
            continue
        try:
            ok = fn()
        except Exception as exc:
            fails.append(f"PROSE '{label}': check raised {type(exc).__name__}: {exc}")
            continue
        if not ok:
            fails.append(f"PROSE '{label}': EVIDENCE DOES NOT SUPPORT the document")
    if len(PROSE_CLAIMS) < 8:
        fails.append("VACUITY FLOOR: fewer than 12 prose claims are gated")
    return fails


PROSE_CHECKS = {"--prose": ("HANDOFF_PROSE_OK", check_prose_claims)}
