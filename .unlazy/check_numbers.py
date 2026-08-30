"""G3: every quantitative claim in the protocol re-derives from source.

ANTI-ECHO, and the earlier version was not. It hardcoded Z_SEL = 1.98,
D_MID = 0.852 - 0.791 and P_BAR = 0.791 at the top of the file -- values retyped
from the entry it was checking (`0.852` appears nowhere in the entry at all,
only the derived difference does) -- and then asserted quantities derived from
them back into that same entry. Two `claims()` calls were pure self-comparison.
The docstring said "no number is parsed out of backlog.txt and compared against
itself", which was literally true (nothing was PARSED) and materially false.

Every input now has an authority outside the text under test:

  * the DISCOVERY row (n, mean price, win rate, z) is PARSED from the PARENT
    backlog entry's own table -- a different entry this one does not control, so
    a disagreement is a real failure rather than a tautology;
  * the FORWARD pick distribution (sd, fee, mean entry, band, rate) is
    recomputed from data/predictions.db by applying the frozen rule;
  * the fee comes from the CFTC-filed formula;
  * the look points come from tracker, which the test module also reads;
  * the haircut, noise floor, power and sample floor are arithmetic on those.

The one input with no external authority is the 1c half-spread. It is not
checked numerically -- it is asserted to be LABELLED an assumption in the entry,
with a pre-committed trigger, rather than sitting silently among derived values.

The haircut table is matched POSITIONALLY (whole row, one regex per row), not by
substring, so the entry's rows cannot be permuted and still pass.
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
import cron  # noqa: E402
import paths  # noqa: E402
import tracker  # noqa: E402

TEXT = (ROOT / "backlog.txt").read_text(encoding="utf-8")
MARKER = "FORWARD-VALIDATION PROTOCOL FOR THE PRICE-RECALIBRATION RULE"
start = TEXT.find(MARKER)
if start < 0:
    print("FAIL: entry not found")
    sys.exit(1)
nxt = re.search(r"\n\[(?:OPEN|DONE|CLOSED) ", TEXT[start:])
ENTRY = TEXT[start : start + (nxt.start() if nxt else len(TEXT) - start)]

GAMMA = 0.5772156649015328606
HALF = 0.01
C_REF = 25
M_DECLARED = 12
FIT_A, FIT_B, THR = -0.12856, 1.33635, 0.05
failures: list[str] = []


def need(cond: bool, msg: str) -> None:
    if not cond:
        failures.append(msg)


def claims(s: str, why: str) -> None:
    need(s in ENTRY, f"{why}: recomputed {s!r} does not appear in the entry")


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


def fee_pc(price: float, C: int = C_REF) -> float:
    """CFTC-filed Kalshi taker fee: round_up_to_cent(0.07*C*P*(1-P)), per contract."""
    return (math.ceil(0.07 * C * price * (1 - price) * 100) / 100) / C


# ================================ A. inputs PARSED from the PARENT entry
parent = TEXT.find("TWO WAYS OUT OF THE NO-EDGE RESULT")
need(parent > 0, "the parent discovery entry is missing from backlog.txt")
row = re.search(
    r"^\s*0\.05\s+(\d+)\s+([\d.]+)\s+([\d.]+)\s+\+([\d.]+)%\s+\+([\d.]+)\s",
    TEXT[parent:] if parent > 0 else "", re.M,
)
if row is None:
    print("FAIL: the parent entry's thr=0.05 discovery row did not parse -- "
          "this checker's inputs have no external authority without it")
    sys.exit(1)
DISC_PRICE = float(row.group(2))
DISC_WIN = float(row.group(3))
Z_SEL = float(row.group(5))
D_MID = DISC_WIN - DISC_PRICE
print(f"  parsed from the PARENT entry: n={row.group(1)} price={DISC_PRICE} "
      f"win={DISC_WIN} z={Z_SEL}  ->  delta_mid={D_MID:+.4f}")

# ============================ B. the forward pick set, recomputed from the DB
db = pathlib.Path(paths.DB_PATH)
con = sqlite3.connect("file:" + db.as_posix() + "?mode=ro", uri=True)
rows = con.execute(
    "SELECT city, condition, target_date, market_prob, outcome "
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


core = [r for r in rows if ctype(r[1]) in {"above", "below", "between"}]


def recal(m):
    m = min(max(m, 1e-6), 1 - 1e-6)
    return 1 / (1 + math.exp(-(FIT_A + FIT_B * math.log(m / (1 - m)))))


picks = []
for r in core:
    m = r[3]
    d = recal(m) - m
    if abs(d) < THR:
        continue
    yes = d > 0
    picks.append({"entry": m if yes else 1 - m, "date": r[2],
                  "side": "YES" if yes else "NO"})

n_pick = len(picks)
mean_entry = sum(q["entry"] for q in picks) / n_pick
sd = math.sqrt(sum((q["entry"] + HALF) * (1 - q["entry"] - HALF) for q in picks) / n_pick)
fee = sum(fee_pc(q["entry"] + HALF) for q in picks) / n_pick
rate = n_pick / len(set(q["date"] for q in picks))
inband = sum(1 for q in picks if 0.74 <= q["entry"] <= 0.86) / n_pick
print(f"  recomputed forward pick set: n={n_pick} "
      f"sides={sorted({q['side'] for q in picks})} mean_mid={mean_entry:.4f} "
      f"a={mean_entry+HALF:.4f} sd={sd:.5f} fee={fee:.5f} rate={rate:.2f}/day "
      f"inband={inband*100:.1f}%")

need({q["side"] for q in picks} == {"NO"},
     "the YES branch now fires -- the addendum's central disclosure is stale")
claims(f"{sd:.5f}", "recomputed sd")
claims(f"{fee:.5f}", "recomputed fee at C=25")
claims(f"{mean_entry:.4f}", "recomputed mean mid entry")
claims(f"{mean_entry + HALF:.4f}", "recomputed mean executable entry")
claims(f"{rate:.2f} picks/day", "recomputed pick rate")
claims(f"{inband*100:.1f}%", "recomputed share inside the 0.74-0.86 band")

# =================================================== C. fee formula (CFTC)
claims("fees = round up(0.07 x C x P x (1-P))", "the filed fee formula verbatim")
claims(f"${0.07*0.79*0.21:.5f}/contract", "unrounded fee at P=0.79")
claims(f"${fee_pc(0.79, 1):.5f}/contract", "fee at P=0.79, C=1")
claims(f"${fee_pc(0.79, 25):.5f}/contract", "fee at P=0.79, C=25")
ratio = fee_pc(0.79, 1) / fee_pc(0.79, 25)
need(abs(ratio - 1.667) < 0.005,
     f"the C=1 vs C=25 ratio at P=0.79 recomputes to {ratio:.3f}, entry says 67%")

# ================================================= D. haircut table (H&L)
praw = p2(Z_SEL)
claims(f"two-sided p = {praw:.4f}", "p-value of the PARSED selection statistic")
claims(f"edge vs the mid +{D_MID:.4f}", "selection edge from the PARENT table")
matched = 0
for M in (3, 4, 6, 10, 12, 20):
    pb = min(M * praw, 1.0)
    zh = ndtri(1 - pb / 2) if pb < 1 else 0.0
    hc = (Z_SEL - zh) / Z_SEL
    dm = D_MID * (1 - hc)
    dn = dm - fee - HALF
    pat = (rf"^\s*{M}\s+{re.escape(f'{hc*100:.1f}')}%\s+"
           rf"{re.escape(f'{dm:+.4f}')}\s+{re.escape(f'{dn:+.4f}')}\s*(<--.*)?$")
    if re.search(pat, ENTRY, re.M):
        matched += 1
    else:
        failures.append(
            f"haircut row M={M} (haircut {hc*100:.1f}%, mid {dm:+.4f}, "
            f"net {dn:+.4f}) does not appear as ONE row in the entry's table"
        )
print(f"  haircut table: {matched}/6 rows recomputed and positionally matched")

Z_CRIT = ndtri(1 - 0.05 / (2 * M_DECLARED))
Z_POW = ndtri(0.80)
claims(f"{Z_CRIT:.4f}", "the M=12 two-sided Bonferroni cut")
claims(f"{ndtri(1 - 0.05 / M_DECLARED):.4f}", "the one-sided cut, quoted for contrast")

# ============================================== E. noise floor and its tail
for N in (3, 4, 6, 10, 12, 20):
    em = (1 - GAMMA) * ndtri(1 - 1.0 / N) + GAMMA * ndtri(1 - 1.0 / (N * math.e))
    claims(f"{em:.3f}", f"E[max z] at N={N}")
    claims(f"{1 - (1 - praw) ** N:.3f}", f"tail probability at N={N}")
print("  noise floor: 6 rows recomputed, both columns")

# =============================================== F. sample floor and looks
delta = D_MID - fee - HALF
n_req = ((Z_CRIT + Z_POW) * sd / delta) ** 2
N_KILL = tracker.PRICE_RECAL_LOOK_2
N_LOOK1 = tracker.PRICE_RECAL_LOOK_1
claims(f"{delta:+.5f}", "delta net of the recomputed fee and the 1c spread")
claims(f"{n_req:,.0f}", "the derived floor")
need(N_KILL >= n_req,
     f"the pre-committed floor {N_KILL} is BELOW the derived {n_req:,.0f}")
need(N_LOOK1 == N_KILL // 2, "look 1 is not half of look 2")
claims(f"N_KILL = {N_KILL:,}", "the pre-committed floor")
claims(f"{N_LOOK1} settled picks", "look 1")
mde = (Z_CRIT + Z_POW) * sd / math.sqrt(N_KILL)
power = ndtr(delta * math.sqrt(N_KILL) / sd - Z_CRIT)
claims(f"{mde:+.4f}", "MDE at the floor")
claims(f"{power*100:.1f}%", "power at the floor")
claims(f"{N_KILL/rate:.0f} days", "accrual at the recomputed rate")
d2 = D_MID - fee - 0.02
claims(f"{d2:+.5f}", "delta at a 2c half-spread")
claims(f"{((Z_CRIT + Z_POW) * sd / d2) ** 2:,.0f}", "floor at a 2c half-spread")
print(f"  floor: derived {n_req:,.0f}, committed {N_KILL}, MDE {mde:+.4f}, "
      f"power {power*100:.1f}%, {N_KILL/rate:.0f} days")

# ======================== G. the futility look, correctly correlated (A-F9)
rho = math.sqrt(N_LOOK1 / N_KILL)
mu1 = delta * math.sqrt(N_LOOK1) / sd
mu2 = delta * math.sqrt(N_KILL) / sd


def bvn_upper(h: float, k: float, r: float, steps: int = 120000) -> float:
    lo = h
    tot = 0.0
    step = 12.0 / steps
    for i in range(steps):
        z1 = lo + (i + 0.5) * step
        phi = math.exp(-0.5 * z1 * z1) / math.sqrt(2 * math.pi)
        tot += phi * (1 - ndtr((k - r * z1) / math.sqrt(1 - r * r))) * step
    return tot


pw_uncond = ndtr(mu2 - Z_CRIT)
pw_joint = bvn_upper(-mu1, Z_CRIT - mu2, rho)
a_joint = bvn_upper(0.0, Z_CRIT, rho)
need(a_joint <= (1 - ndtr(Z_CRIT)) + 1e-6,
     f"the futility look INFLATES alpha: {a_joint:.6f} vs {1-ndtr(Z_CRIT):.6f}")
claims(f"{pw_uncond:.5f}", "unconditional power")
claims(f"{pw_joint:.5f}", "joint power across both looks")
claims(f"{a_joint:.6f}", "type-I error across both looks")
need(f"{pw_uncond - pw_joint:.5f}" in ENTRY,
     f"the futility look's power cost recomputes to {pw_uncond-pw_joint:.5f}; "
     f"the entry must state that value, not a product of the two marginals")
print(f"  futility: rho={rho:.4f} power {pw_uncond:.5f} -> {pw_joint:.5f} "
      f"(cost {pw_uncond-pw_joint:.5f}), alpha {a_joint:.6f}")

# ============================================ H. the unverified assumption
need("THE 1c HALF-SPREAD IS AN ASSUMPTION, NOT A MEASUREMENT" in ENTRY,
     "the 1c half-spread has no external authority and must be labelled an "
     "assumption, not left among derived quantities")
need("PRE-COMMITTED TRIGGER" in ENTRY,
     "no pre-committed rule for what happens if the spread measures wider")

# ========================================= I. frozen coefficients vs the DB
def fit(sample):
    xs = [math.log(min(max(r[3], 1e-6), 1-1e-6) / (1 - min(max(r[3], 1e-6), 1-1e-6)))
          for r in sample]
    ys = [float(r[4]) for r in sample]
    a, b = 0.0, 1.0
    for _ in range(300):
        g0 = g1 = h00 = h01 = h11 = 0.0
        for x, y in zip(xs, ys):
            pr = 1 / (1 + math.exp(-max(min(a + b * x, 40), -40)))
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
    return a, b


a_f, b_f = fit(core)
print(f"  population: {len(rows)} rows, core {len(core)}; refit a={a_f:+.5f} "
      f"b={b_f:+.5f} (frozen {FIT_A:+.5f}/{FIT_B:+.5f}, drift {abs(b_f-FIT_B):.5f})")
need(abs(b_f - FIT_B) <= 0.01 and abs(a_f - FIT_A) <= 0.01,
     f"the frozen coefficients no longer reproduce from the entry's own stated "
     f"population definition (refit a={a_f:+.5f} b={b_f:+.5f})")
claims(f"a = {FIT_A:.5f}", "frozen intercept")
claims(f"b = +{FIT_B:.5f}", "frozen slope")

need(cron._PRICE_RECAL_FIT_A == FIT_A, "cron's intercept differs from the entry's")
need(cron._PRICE_RECAL_FIT_B == FIT_B, "cron's slope differs from the entry's")
need(cron._PRICE_RECAL_THRESHOLD == THR, "cron's threshold differs from the entry's")
need(f'"{cron._PRICE_RECAL_PROTOCOL_VERSION}"' in ENTRY,
     f"the protocol version {cron._PRICE_RECAL_PROTOCOL_VERSION!r} stamped on every "
     f"row does not appear in the entry, so the stamp has no external authority")

if failures:
    for f in failures:
        print(f"FAIL: {f}")
    sys.exit(1)
print("GATE_G3_PASS")
