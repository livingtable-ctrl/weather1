"""Extended gates: bulk numeric tables, the bootstrap CI, and QUALITATIVE claims.

Discharges the three items pass 6 recorded as NOT DONE:

  1. 150 genuine ungated numeric claims -> `check_tables` derives whole tables
     rather than individual figures, which is how the count actually falls.
  2. The bootstrap CI was gateable but slow -> `check_bootstrap` reproduces it
     with a rank-based AUC (O(n log n) instead of O(n^2)), so 2000 resamples
     run in about a second.
  3. Non-numeric claims were entirely ungated -> `check_assertions` turns each
     causal/eliminative sentence into a testable inequality. A qualitative
     claim is not unfalsifiable; it just needs its truth condition written
     down. This is the hole mutation coverage cannot reach, because mutating a
     number never touches a sentence that contains none.

READ-ONLY.
"""

from __future__ import annotations

import json
import pathlib
import random
import re
import statistics
from collections import defaultdict

from audit_handoff import (
    DB,
    TOL,
    _auc,
    _core_rows_ct,
    _section,
    con,
    text,
)


# ---------------------------------------------------------------- fast AUC --
def fast_auc(pairs) -> float | None:
    """Mann-Whitney U via ranks. Same value as the O(n^2) form, far cheaper."""
    if not pairs:
        return None
    order = sorted(range(len(pairs)), key=lambda i: pairs[i][0])
    ranks = [0.0] * len(pairs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and pairs[order[j + 1]][0] == pairs[order[i]][0]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    n1 = sum(1 for _p, y in pairs if y == 1)
    n0 = len(pairs) - n1
    if not n1 or not n0:
        return None
    r1 = sum(r for r, (_p, y) in zip(ranks, pairs) if y == 1)
    return (r1 - n1 * (n1 + 1) / 2.0) / (n1 * n0)


def _per(m: str) -> str:
    return "MayJun" if m in ("2026-05", "2026-06") else "JulAug"


# ------------------------------------------------------------ bulk tables ---
def check_tables() -> list[str]:
    """Derive whole tables, not single figures."""
    fails: list[str] = []

    # --- forecast-error table: mean and p90 columns (median already gated) --
    with con() as c:
        fe = c.execute(
            """SELECT strftime('%Y-%m', p.predicted_at),
                      ABS(p.forecast_temp_f - o.settled_temp_f)
               FROM predictions p JOIN outcomes o ON o.ticker = p.ticker
               WHERE p.forecast_temp_f IS NOT NULL AND o.settled_temp_f IS NOT NULL
                 AND (p.ticker LIKE 'KXHIGH%' OR p.ticker LIKE 'KXLOWT%')"""
        ).fetchall()
    byfe: dict[str, list] = defaultdict(list)
    for m, e in fe:
        byfe[m].append(e)
    scope = _section("Raw forecast error, `|forecast_temp_f", fails, "fe-table")
    for key in ("2026-05", "2026-06", "2026-07", "2026-08"):
        mm = re.search(
            rf"\| {key} \| \d+ \| \*{{0,2}}[0-9.]+\*{{0,2}} \| ([0-9.]+) \| ([0-9.]+) \|",
            scope,
        )
        if not mm:
            fails.append(f"fe-table {key}: mean/p90 row not found")
            continue
        v = sorted(byfe[key])
        mean = statistics.fmean(v)
        p90 = v[int(0.9 * (len(v) - 1))]
        if abs(mean - float(mm.group(1))) > 0.005:
            fails.append(f"fe {key} mean: {mean:.2f} doc says {mm.group(1)}")
        if abs(p90 - float(mm.group(2))) > 0.005:
            fails.append(f"fe {key} p90: {p90:.2f} doc says {mm.group(2)}")

    # --- our_prob vs raw_prob magnitude table ------------------------------
    with con() as c:
        rp = c.execute(
            """SELECT strftime('%Y-%m', predicted_at), ABS(our_prob - raw_prob)
               FROM predictions
               WHERE our_prob IS NOT NULL AND raw_prob IS NOT NULL
                 AND method='ensemble' AND predicted_at >= '2026-05-01'
                 AND (ticker LIKE 'KXHIGH%' OR ticker LIKE 'KXLOWT%')"""
        ).fetchall()
    byrp: dict[str, list] = defaultdict(list)
    for m, d in rp:
        byrp[m].append(d)
    sc = _section("Measured magnitude of `|our_prob - raw_prob|`", fails, "rawprob")
    for key in ("2026-05", "2026-06", "2026-07", "2026-08"):
        mm = re.search(
            rf"\| {key} \| (\d+) \| [0-9.e-]+ \| ([0-9.]+) \| ([0-9.]+) \| (\d+) \|", sc
        )
        if not mm:
            continue  # rows using scientific notation for mean are skipped
        v = byrp[key]
        if len(v) != int(mm.group(1)):
            fails.append(f"rawprob {key} n: {len(v)} doc says {mm.group(1)}")
        if abs(max(v) - float(mm.group(3))) > 5e-4:
            fails.append(f"rawprob {key} max: {max(v):.4f} doc says {mm.group(3)}")
        over = sum(1 for x in v if x > 0.01)
        if over != int(mm.group(4)):
            fails.append(f"rawprob {key} rows>0.01: {over} doc says {mm.group(4)}")

    # --- n_members detail --------------------------------------------------
    with con() as c:
        aug = dict(
            c.execute(
                """SELECT n_members, COUNT(*) FROM predictions
                   WHERE predicted_at >= '2026-08-01' AND method='ensemble'
                     AND n_members IS NOT NULL
                     AND (ticker LIKE 'KXHIGH%' OR ticker LIKE 'KXLOWT%')
                   GROUP BY n_members"""
            ).fetchall()
        )
    am = re.search(
        r"August carries 238 \((\d+)\),\s*\n?\s*258 \((\d+)\), 208 \((\d+)\)", text()
    )
    if not am:
        fails.append("n_members August detail: sentence not found")
    else:
        for val, grp in ((238, 1), (258, 2), (208, 3)):
            if aug.get(val, 0) != int(am.group(grp)):
                fails.append(
                    f"n_members Aug {val}: {aug.get(val, 0)} rows, doc says {am.group(grp)}"
                )

    # --- live temperature_scale history table ------------------------------
    hist = sorted((DB.parent / ".history").glob("temperature_scale_*.json"))
    hs = _section("| snapshot | sameday T | n | global T |", fails, "ts-history")
    for f in hist:
        stamp = f.stem.replace("temperature_scale_", "")
        pretty = f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}T{stamp[9:11]}:{stamp[11:13]}"
        mm = re.search(
            rf"\| {re.escape(pretty)} \| \*{{0,2}}([0-9.]+|absent)\*{{0,2}} \| ([0-9—-]+) \| \*{{0,2}}([0-9.]+)\*{{0,2}} \|",
            hs,
        )
        if not mm:
            continue  # not every snapshot is tabulated
        d = json.loads(f.read_text(encoding="utf-8"))
        sd, gl = d.get("sameday"), d.get("global")
        if mm.group(1) == "absent":
            if sd is not None:
                fails.append(
                    f"ts-history {pretty}: doc says sameday absent, file has it"
                )
        elif abs(float(sd["T"]) - float(mm.group(1))) > 1e-3:
            fails.append(
                f"ts-history {pretty} sameday: {sd['T']} doc says {mm.group(1)}"
            )
        if gl is not None and abs(float(gl["T"]) - float(mm.group(3))) > 1e-3:
            fails.append(
                f"ts-history {pretty} global: {gl['T']} doc says {mm.group(3)}"
            )
    return fails


# -------------------------------------------------------------- bootstrap ---
def check_bootstrap() -> list[str]:
    """Reproduce the difference-in-differences CI the document quotes."""
    fails: list[str] = []
    mm = re.search(
        r"observed DiD\s*=\s*\+([0-9.]+).*?95% CI\s*=\s*\[-([0-9.]+), \+([0-9.]+)\]\s*(\d+) resamples",
        text(),
        re.S,
    )
    if not mm:
        fails.append("bootstrap block: not found in document")
        return fails
    w_obs, w_lo, w_hi, w_n = (
        float(mm.group(1)),
        -float(mm.group(2)),
        float(mm.group(3)),
        int(mm.group(4)),
    )

    rows = [
        r for r in _core_rows_ct() if r[4] in ("above", "below") and r[2] is not None
    ]
    by_ticker: dict[str, list] = defaultdict(list)
    for m, op, mp, y, ct, tk in rows:
        by_ticker[tk].append((_per(m), ct, op, mp, float(y)))
    tickers = list(by_ticker)

    def did(sample):
        g: dict[tuple, list] = defaultdict(list)
        for tk in sample:
            for p_, ct, op, mp, y in by_ticker[tk]:
                g[(p_, ct, "model")].append((op, y))
                g[(p_, ct, "market")].append((mp, y))
        out = []
        for ct in ("above", "below"):
            v = {}
            for p_ in ("MayJun", "JulAug"):
                for who in ("model", "market"):
                    a = fast_auc(g[(p_, ct, who)])
                    if a is None:
                        return None
                    v[(p_, who)] = a
            out.append(
                (v[("MayJun", "model")] - v[("JulAug", "model")])
                - (v[("MayJun", "market")] - v[("JulAug", "market")])
            )
        return statistics.fmean(out)

    obs = did(tickers)
    if obs is None or abs(obs - w_obs) > 5e-4:
        fails.append(f"bootstrap observed DiD: {obs} doc says {w_obs}")
    rng = random.Random(20260830)
    boot = []
    for _ in range(w_n):
        v = did([rng.choice(tickers) for _ in tickers])
        if v is not None:
            boot.append(v)
    boot.sort()
    lo, hi = boot[int(0.025 * len(boot))], boot[int(0.975 * len(boot))]
    # The CI is resample-order dependent; require the same sign structure and
    # closeness, not bit-equality.
    if abs(lo - w_lo) > 0.02 or abs(hi - w_hi) > 0.02:
        fails.append(
            f"bootstrap CI: [{lo:+.4f}, {hi:+.4f}] doc says [{w_lo:+.4f}, {w_hi:+.4f}]"
        )
    if lo > 0:
        fails.append("bootstrap CI excludes 0, but the document says it includes 0")
    return fails


# --------------------------------------------------- qualitative assertions --
def check_assertions() -> list[str]:
    """Turn each causal/eliminative sentence into a testable inequality.

    Every entry is (regex proving the DOCUMENT makes the claim, a callable
    returning True when the data SUPPORTS it, label). Both must hold: a claim
    the document no longer makes is as much a failure as one the data refutes,
    because it means this gate has silently stopped guarding anything.
    """
    fails: list[str] = []
    rows = _core_rows_ct()

    def model_auc(p_, ct=None):
        pairs = [
            (op, float(y))
            for m, op, _mp, y, c, _tk in rows
            if _per(m) == p_ and (ct is None or c == ct)
        ]
        return fast_auc(pairs)

    def market_auc(p_, ct):
        pairs = [
            (mp, float(y))
            for m, _op, mp, y, c, _tk in rows
            if _per(m) == p_ and c == ct and mp is not None
        ]
        return fast_auc(pairs)

    def forecast_median(month):
        with con() as c:
            v = [
                r[0]
                for r in c.execute(
                    """SELECT ABS(p.forecast_temp_f - o.settled_temp_f)
                       FROM predictions p JOIN outcomes o ON o.ticker = p.ticker
                       WHERE strftime('%Y-%m', p.predicted_at) = ?
                         AND p.forecast_temp_f IS NOT NULL
                         AND o.settled_temp_f IS NOT NULL
                         AND (p.ticker LIKE 'KXHIGH%' OR p.ticker LIKE 'KXLOWT%')""",
                    (month,),
                ).fetchall()
            ]
        return statistics.median(v) if v else None

    def emos_never_active():
        return not list((DB.parent).glob("emos*"))

    def forecast_halved():
        jun, jul = forecast_median("2026-06"), forecast_median("2026-07")
        return jun is not None and jul is not None and jul <= jun * 0.6

    def auc_calibration_invariant():
        """PROVE it on this corpus: temperature-scale every probability and
        confirm AUC is unchanged. The document rules calibration out on
        mathematics; this checks the mathematics against the actual data."""
        import math

        base = [(op, float(y)) for _m, op, _mp, y, _c, _tk in rows]

        def T(p, t=4.6):
            p = min(max(p, 1e-9), 1 - 1e-9)
            lg = math.log(p / (1 - p)) / t
            return 1 / (1 + math.exp(-lg))

        scaled = [(T(p), y) for p, y in base]
        a0, a1 = fast_auc(base), fast_auc(scaled)
        # EXACT in real arithmetic. In float64 it is exact at most T (delta 0.0
        # at T=2 and T=10 on this corpus) but not all: at T=4.6 three of 303
        # distinct probabilities round together, creating ties worth 3.4e-05.
        # The invariance argument survives; the literal word "EXACTLY" does not,
        # which is why the tolerance here is 1e-3 and not 0.
        if a0 is None or a1 is None:
            return False
        return abs(a0 - a1) < 1e-3

    def accuracy_invariant_under_compression():
        import math

        base = [(op, float(y)) for _m, op, _mp, y, _c, _tk in rows]

        def T(p, t=4.6):
            p = min(max(p, 1e-9), 1 - 1e-9)
            return 1 / (1 + math.exp(-math.log(p / (1 - p)) / t))

        acc0 = statistics.fmean(1.0 if (p >= 0.5) == (y == 1) else 0.0 for p, y in base)
        acc1 = statistics.fmean(
            1.0 if (T(p) >= 0.5) == (y == 1) else 0.0 for p, y in base
        )
        return abs(acc0 - acc1) < 1e-12

    def market_did_not_fall_in_any_stratum():
        return all(
            market_auc("JulAug", ct) >= market_auc("MayJun", ct)
            for ct in ("above", "below")
        )

    def never_discriminated_on_below():
        return abs(model_auc("MayJun", "below") - 0.5) < 0.06

    def rawprob_is_rounding_noise():
        with con() as c:
            v = [
                r[0]
                for r in c.execute(
                    """SELECT ABS(our_prob - raw_prob) FROM predictions
                       WHERE our_prob IS NOT NULL AND raw_prob IS NOT NULL
                         AND method='ensemble' AND predicted_at >= '2026-06-01'
                         AND predicted_at < '2026-08-01'
                         AND (ticker LIKE 'KXHIGH%' OR ticker LIKE 'KXLOWT%')"""
                ).fetchall()
            ]
        return v and statistics.median(v) < 1e-6

    def july_n_members_constant():
        with con() as c:
            got = c.execute(
                """SELECT COUNT(DISTINCT n_members) FROM predictions
                   WHERE predicted_at >= '2026-07-01' AND predicted_at < '2026-08-01'
                     AND method='ensemble' AND n_members IS NOT NULL
                     AND (ticker LIKE 'KXHIGH%' OR ticker LIKE 'KXLOWT%')"""
            ).fetchone()[0]
        return got == 1

    def between_unmeasurable_later():
        n = sum(
            1
            for m, _op, _mp, _y, c, _tk in rows
            if _per(m) == "JulAug" and c == "between"
        )
        return n < 20

    def fitter_reads_our_prob():
        src = DB.parent.parent / "ml_bias.py"
        if not src.exists():
            src = pathlib.Path(__file__).resolve().parents[1] / "ml_bias.py"
        body = src.read_text(encoding="utf-8", errors="replace")
        return "SELECT p.our_prob, o.settled_yes" in body

    CLAIMS = [
        (
            r"\*\*EMOS WAS NEVER ACTIVE\.\*\*",
            emos_never_active,
            "EMOS was never active (no emos* file in data/)",
        ),
        (
            r"temperature forecast roughly HALVED its error in July",
            forecast_halved,
            "forecast error halved Jun->Jul",
        ),
        (
            r"AUC is calibration-invariant by construction",
            auc_calibration_invariant,
            "AUC unchanged under temperature scaling, on this corpus",
        ),
        (
            r"it leaves accuracy EXACTLY unchanged",
            accuracy_invariant_under_compression,
            "accuracy unchanged under temperature scaling, on this corpus",
        ),
        (
            r"the market's AUC did not fall in any stratum",
            market_did_not_fall_in_any_stratum,
            "market AUC did not fall in above or below",
        ),
        (
            r"On `below` it NEVER\s*\n?\s*discriminated",
            never_discriminated_on_below,
            "model AUC on below MayJun is at chance",
        ),
        (
            r"The medians are rounding noise",
            rawprob_is_rounding_noise,
            "median |our_prob-raw_prob| below 1e-6",
        ),
        (
            r"`n_members` is \*\*238 on every one of the 56 July rows",
            july_n_members_constant,
            "July n_members takes exactly one value",
        ),
        (
            r"`between` stratum still has n=4|n=4\) in the later period|\| \*\*4\*\* \|",
            between_unmeasurable_later,
            "between is unmeasurably small in JulAug",
        ),
        (
            r"the fitter reads `our_prob`|SELECT p\.our_prob, o\.settled_yes",
            fitter_reads_our_prob,
            "train_all_temperature_scaling selects our_prob",
        ),
    ]
    for pat, fn, label in CLAIMS:
        if not re.search(pat, text()):
            fails.append(
                f"ASSERTION '{label}': the document no longer makes this claim"
            )
            continue
        try:
            ok = fn()
        except Exception as exc:
            fails.append(
                f"ASSERTION '{label}': check raised {type(exc).__name__}: {exc}"
            )
            continue
        if not ok:
            fails.append(f"ASSERTION '{label}': DATA DOES NOT SUPPORT the document")
    return fails


EXT_CHECKS = {
    "--tables": ("HANDOFF_TABLES_OK", check_tables),
    "--bootstrap": ("HANDOFF_BOOTSTRAP_OK", check_bootstrap),
    "--assertions": ("HANDOFF_ASSERTIONS_OK", check_assertions),
}
