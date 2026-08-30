"""G3: every quantitative claim in the protocol re-derives from source.

ANTI-ECHO. Each figure is recomputed here from data/predictions.db or from the
CFTC-filed fee formula and THEN compared against the entry's text. No number is
parsed out of backlog.txt and compared against itself.

Two classes of figure, checked differently on purpose:
  * ARITHMETIC (haircuts, noise floor, sample floor, fee, power) is
    deterministic and is asserted exactly at the stated precision.
  * POPULATION figures come from a table the cron appends to daily, so they
    drift. They are asserted against a re-fit of the entry's own stated
    population definition, with an explicit tolerance, and the observed drift is
    printed either way. Drift beyond tolerance is a real finding, not a flaky
    test: it means the frozen coefficients no longer describe the population the
    entry says they were fitted on.
"""

from __future__ import annotations

import ast
import math
import pathlib
import re
import sqlite3
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import paths  # noqa: E402

TEXT = (ROOT / "backlog.txt").read_text(encoding="utf-8")
MARKER = "FORWARD-VALIDATION PROTOCOL FOR THE PRICE-RECALIBRATION RULE"
start = TEXT.find(MARKER)
if start < 0:
    print("FAIL: entry not found")
    sys.exit(1)
nxt = re.search(r"\n\[(?:OPEN|DONE|CLOSED) ", TEXT[start:])
ENTRY = TEXT[start : start + (nxt.start() if nxt else len(TEXT) - start)]

GAMMA = 0.5772156649015328606
failures: list[str] = []


def need(cond: bool, msg: str) -> None:
    if not cond:
        failures.append(msg)


def claims(s: str, why: str) -> None:
    """Assert the recomputed string `s` literally appears in the entry."""
    need(s in ENTRY, f"{why}: recomputed {s!r} does not appear in the entry")


# ----------------------------------------------------------------- primitives
def ndtri(p: float) -> float:
    a = [-3.969683028665376e01, 2.209460984245205e02, -2.759285104469687e02,
         1.383577518672690e02, -3.066479806614716e01, 2.506628277459239e00]
    b = [-5.447609879822406e01, 1.615858368580409e02, -1.556989798598866e02,
         6.680131188771972e01, -1.328068155288572e01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e00,
         -2.549732539343734e00, 4.374664141464968e00, 2.938163982698783e00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00,
         3.754408661907416e00]
    pl = 0.02425
    if p < pl:
        q = math.sqrt(-2 * math.log(p))
        return ((((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5])
                / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1))
    if p > 1 - pl:
        q = math.sqrt(-2 * math.log(1 - p))
        return -((((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5])
                 / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1))
    q = p - 0.5
    r = q * q
    return ((((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q
            / (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1))


def ndtr(z: float) -> float:
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def p2(z: float) -> float:
    return 2 * (1 - ndtr(abs(z)))


def logit(x: float) -> float:
    x = min(max(x, 1e-6), 1 - 1e-6)
    return math.log(x / (1 - x))


# =========================================================== A. fee (CFTC form)
# fees = round up(0.07 x C x P x (1-P)); round up = to the next cent.
def fee_pc(price: float, C: int) -> float:
    return (math.ceil(0.07 * C * price * (1 - price) * 100) / 100) / C


unrounded = 0.07 * 0.79 * (1 - 0.79)
claims(f"${unrounded:.5f}/contract", "fee at P=0.79 unrounded")
claims(f"${fee_pc(0.79, 1):.5f}/contract", "fee at P=0.79, C=1")
claims(f"${fee_pc(0.79, 25):.5f}/contract", "fee at P=0.79, C=25")
need(
    abs(fee_pc(0.79, 1) / unrounded - 1.72) < 0.005,
    f"C=1 rounding multiple recomputes to {fee_pc(0.79, 1) / unrounded:.2f}, entry says 1.72x",
)
claims("fees = round up(0.07 x C x P x (1-P))", "the filed fee formula verbatim")
print(f"  fee P=0.79: unrounded ${unrounded:.5f}  C=1 ${fee_pc(0.79, 1):.5f}  "
      f"C=25 ${fee_pc(0.79, 25):.5f}")

# ================================================= B. haircut table (Harvey&Liu)
Z_SEL, D_MID, P_BAR, HALF, C_REF = 1.98, 0.852 - 0.791, 0.791, 0.01, 25
a_exec = P_BAR + HALF
fee = fee_pc(a_exec, C_REF)
sd = math.sqrt(a_exec * (1 - a_exec))
claims(f"a = {a_exec:.4f}", "mean executable entry")
claims(f"sd      = {sd:.4f}", "per-pick sd")

p_raw = p2(Z_SEL)
need(abs(p_raw - 0.0477) < 5e-5, f"two-sided p at z=1.98 recomputes to {p_raw:.4f}")
claims("two-sided p = 0.0477", "p-value of the selection statistic")
claims(f"edge vs the mid +{D_MID:.4f}", "selection edge vs the mid")

for M, hc_txt, dmid_txt, dnet_txt in (
    (3, "26.0%", "+0.0451", "+0.0239"),
    (4, "33.9%", "+0.0403", "+0.0191"),
    (6, "46.1%", "+0.0329", "+0.0117"),
    (10, "64.1%", "+0.0219", "+0.0007"),
    (20, "97.1%", "+0.0018", "-0.0194"),
):
    p_bon = min(M * p_raw, 1.0)
    z_hc = ndtri(1 - p_bon / 2) if p_bon < 1 else 0.0
    hc = (Z_SEL - z_hc) / Z_SEL
    d_mid = D_MID * (1 - hc)
    d_net = d_mid - fee - HALF
    need(f"{hc * 100:.1f}%" == hc_txt,
         f"M={M} haircut recomputes to {hc * 100:.1f}%, entry says {hc_txt}")
    need(f"{d_mid:+.4f}" == dmid_txt,
         f"M={M} edge-vs-mid recomputes to {d_mid:+.4f}, entry says {dmid_txt}")
    need(f"{d_net:+.4f}" == dnet_txt,
         f"M={M} net edge recomputes to {d_net:+.4f}, entry says {dnet_txt}")
    claims(hc_txt, f"M={M} haircut appears in the table")
    claims(dmid_txt, f"M={M} edge-vs-mid appears in the table")
    claims(dnet_txt, f"M={M} net edge appears in the table")
print("  haircut table: 5 rows recomputed and matched")

Z_CRIT = ndtri(1 - 0.05 / (2 * 10))
need(f"{Z_CRIT:.3f}" == "2.807", f"HL Bonferroni t-cut recomputes to {Z_CRIT:.3f}")
claims("|z| >= 2.807", "the Bonferroni decision threshold")

# ============================================ C. noise floor (DSR expected max)
for N, want in ((3, "0.853"), (4, "1.052"), (6, "1.300"), (10, "1.575"), (20, "1.901")):
    em = (1 - GAMMA) * ndtri(1 - 1.0 / N) + GAMMA * ndtri(1 - 1.0 / (N * math.e))
    need(f"{em:.3f}" == want, f"E[max z] at N={N} recomputes to {em:.3f}, entry says {want}")
    claims(want, f"noise floor at N={N}")
print("  noise floor: 5 values recomputed and matched")

# ================================================== D. sample floor (power calc)
Z_POW = ndtri(0.80)
need(f"{Z_POW:.3f}" == "0.842", f"z_power recomputes to {Z_POW:.3f}")
for M, want_n in ((1, "1,340"), (4, "5,815")):
    if M == 1:
        d = D_MID - fee - HALF
    else:
        p_bon = min(M * p_raw, 1.0)
        d = D_MID * (ndtri(1 - p_bon / 2) / Z_SEL) - fee - HALF
    n = ((Z_CRIT + Z_POW) * sd / d) ** 2
    need(f"{n:,.0f}" == want_n, f"n at M={M} recomputes to {n:,.0f}, entry says {want_n}")
    claims(want_n, f"sample floor at M={M}")
d_raw = D_MID - fee - HALF
mde = (Z_CRIT + Z_POW) * sd / math.sqrt(1340)
need(abs(mde - d_raw) < 5e-4,
     f"MDE at N_KILL ({mde:+.4f}) must equal the edge it was sized on ({d_raw:+.4f})")
claims(f"is +{mde:.4f}", "MDE at 1,340 picks")
print(f"  sample floor: N_KILL=1,340 sized on delta={d_raw:+.4f}, MDE={mde:+.4f}")

# 60-day claim in the superseded option-5 status line
mde60 = (Z_CRIT + Z_POW) * sd / math.sqrt(384)
need(f"{mde60:+.3f}" == "+0.074",
     f"60-day MDE recomputes to {mde60:+.3f}, cross-reference says +0.074")
need(mde60 > 0.0610,
     f"the 60-day MDE ({mde60:+.4f}) must exceed the discovery edge (+0.0610) "
     f"for the cross-reference argument to hold")

# ============================================================ E. futility power
mu = d_raw * math.sqrt(670) / sd
power_kept = 0.80 * (1 - ndtr(-mu))
need(f"{power_kept:.3f}" == "0.796",
     f"retained power recomputes to {power_kept:.3f}, entry says 0.796")
claims("0.800 -> 0.796", "the measured power cost of the futility look")
claims(f"P(stop | H1) = {ndtr(-mu):.3f}", "futility stop probability under H1")
print(f"  futility look at 670: E[z|H1]={mu:.3f} power kept {power_kept:.3f}")

# ==================================================== F. population (drifts)
db = pathlib.Path(paths.DB_PATH)
con = sqlite3.connect("file:" + db.as_posix() + "?mode=ro", uri=True)
rows = con.execute(
    "SELECT city, condition, target_date, market_prob, days_out, outcome "
    "FROM analysis_attempts WHERE outcome IS NOT NULL "
    "AND forecast_prob IS NOT NULL AND market_prob IS NOT NULL "
    "AND target_date <= '2026-08-29'"
).fetchall()
con.close()


def ctype(c):
    try:
        return ast.literal_eval(c).get("type")
    except Exception:
        return None


def cvar(c):
    try:
        return ast.literal_eval(c).get("var")
    except Exception:
        return None


core = [r for r in rows if ctype(r[1]) in {"above", "below", "between"}]


def fit(sample):
    xs = [logit(r[3]) for r in sample]
    ys = [float(r[5]) for r in sample]
    a, b = 0.0, 1.0
    for _ in range(300):
        g0 = g1 = h00 = h01 = h11 = 0.0
        for x, y in zip(xs, ys):
            pr = 1.0 / (1.0 + math.exp(-max(min(a + b * x, 40), -40)))
            g0 += y - pr
            g1 += (y - pr) * x
            w = pr * (1 - pr)
            h00 += w
            h01 += w * x
            h11 += w * x * x
        det = h00 * h11 - h01 * h01
        da = (h11 * g0 - h01 * g1) / det
        db = (h00 * g1 - h01 * g0) / det
        a += da
        b += db
        if abs(da) < 1e-13 and abs(db) < 1e-13:
            break
    return a, b, math.sqrt(h00 / det)


a_f, b_f, se_f = fit(core)
FROZEN_A, FROZEN_B, TOL = -0.12856, 1.33635, 0.01
print(f"  population: {len(rows)} rows, core {len(core)}")
print(f"  refit: a={a_f:+.5f} b={b_f:+.5f} SE={se_f:.5f} z={(b_f - 1) / se_f:+.3f}")
print(f"  frozen: a={FROZEN_A:+.5f} b={FROZEN_B:+.5f}   "
      f"drift b={abs(b_f - FROZEN_B):.5f} (tol {TOL})")
need(
    abs(b_f - FROZEN_B) <= TOL and abs(a_f - FROZEN_A) <= TOL,
    f"the frozen coefficients no longer reproduce from the entry's own stated "
    f"population definition (refit a={a_f:+.5f} b={b_f:+.5f} vs frozen "
    f"a={FROZEN_A:+.5f} b={FROZEN_B:+.5f}). Either the population definition in "
    f"section 1 is wrong or late settlements have moved it materially.",
)
claims(f"a = {FROZEN_A:.5f}", "frozen intercept")
claims(f"b = +{FROZEN_B:.5f}", "frozen slope")

events_cd = len({(r[0], r[2]) for r in core})
events_cdv = len({(r[0], r[2], cvar(r[1])) for r in core})
print(f"  events: (city,date)={events_cd}  (city,date,var)={events_cdv}  "
      f"rows/city-day={len(core) / events_cd:.2f}")
need(
    abs(len(core) / events_cd - 1.45) < 0.05,
    f"rows per city-day recomputes to {len(core) / events_cd:.2f}, entry says 1.45",
)
claims("1.45 rows per city-day", "the clustering ratio")

if failures:
    for f in failures:
        print(f"FAIL: {f}")
    sys.exit(1)
print("GATE_G3_PASS")
