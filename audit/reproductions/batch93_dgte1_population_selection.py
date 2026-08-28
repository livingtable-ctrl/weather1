"""Reproduce batch-93's answer to "is the d>=1 calibration population selected?"

Run:  python audit/reproductions/batch93_dgte1_population_selection.py

WHAT THIS SETTLES. The backlog entry asked whether `days_out >= 1` selects
markets whose LAST scan was multi-day, and proposed reconstructing per-market
scan histories from api_requests or cron.log to define the population by
FIRST-scan horizon instead.

Section 1 shows that method CANNOT WORK, and would have produced a
confidently wrong answer. Section 2 answers the underlying question a
different way -- by measuring the selection's IMPACT rather than removing it.

ISOLATION (same discipline as batch89_exit_rule_measurements.py):
  * predictions.db is opened `file:...?mode=ro`, so this cannot write.
  * tracker/ml_bias are deliberately NOT imported -- importing them runs
    init_db(), which writes. The Platt fit is reimplemented here instead.
  * DATA_DIR comes from paths.py, not from __file__: in a worktree the code
    lives under .claude/worktrees/<name>/ while paths resolves data/ back to
    the MAIN clone.

METHOD NOTES:
  * The population mirrors tracker.get_analysis_calibration_data exactly:
    outcome/forecast_prob/market_prob NOT NULL, days_out >= 1, ticker LIKE
    the _DAILY_TEMP_TICKER_PREFIXES, 'between' excluded, and the calibrated
    column is COALESCE(forecast_prob_precal, forecast_prob).
  * The train/test comparison is OUT-OF-SAMPLE and chronological. In-sample
    it looks like a 15pp distortion; out-of-sample that vanishes. Reporting
    the in-sample number alone would have been wrong.
  * The population is NOT pinned to a date here (unlike batch-89): the whole
    point is a live-state question and the answer is expected to sharpen as
    n grows. EXPECTED_N records what batch-93 saw so a reader can tell
    "grown" from "changed".
"""

from __future__ import annotations

import ast
import math
import random
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from paths import CRON_LOG_PATH, DATA_DIR  # noqa: E402

PRED_DB = DATA_DIR / "predictions.db"
EXPECTED_N = 195  # core d>=1 rows as of 2026-08-27
EPS = 1e-6


def _ro(p: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True)


def _ctype(s: str | None) -> str:
    try:
        return (ast.literal_eval(s) or {}).get("type", "") if s else ""
    except Exception:
        return ""


def load_fit_population() -> list[dict]:
    con = _ro(PRED_DB)
    con.row_factory = sqlite3.Row
    rows = [
        dict(r)
        for r in con.execute(
            """
            SELECT ticker,
                   COALESCE(forecast_prob_precal, forecast_prob) AS p,
                   market_prob AS m, outcome AS y, condition, analyzed_at
            FROM analysis_attempts
            WHERE outcome IS NOT NULL AND forecast_prob IS NOT NULL
              AND market_prob IS NOT NULL AND days_out >= 1
              AND (ticker LIKE 'KXHIGH%' OR ticker LIKE 'KXLOWT%')
            ORDER BY analyzed_at
            """
        )
    ]
    con.close()
    return [r for r in rows if _ctype(r["condition"]) != "between"]


def _logit(p: float) -> float:
    p = min(max(p, EPS), 1 - EPS)
    return math.log(p / (1 - p))


def fit_platt(sub: list[dict], iters: int = 4000, lr: float = 0.05):
    """sigmoid(a*logit(p)+b) by gradient descent on log-loss."""
    a, b = 1.0, 0.0
    xs = [_logit(r["p"]) for r in sub]
    ys = [float(r["y"]) for r in sub]
    for _ in range(iters):
        ga = gb = 0.0
        for x, y in zip(xs, ys):
            s = 1 / (1 + math.exp(-max(-30, min(30, a * x + b))))
            ga += (s - y) * x
            gb += s - y
        a -= lr * ga / len(xs)
        b -= lr * gb / len(xs)
    return a, b


def cal(p: float, a: float, b: float) -> float:
    return 1 / (1 + math.exp(-max(-30, min(30, a * _logit(p) + b))))


def brier(sub, a, b) -> float:
    return sum((cal(r["p"], a, b) - r["y"]) ** 2 for r in sub) / len(sub)


def section_1_why_the_proposed_method_fails(pop) -> None:
    print("1. CAN SCAN HISTORY BE RECONSTRUCTED? (the entry's proposed method)")
    print("   Test: is the candidate source's COVERAGE independent of the very")
    print("   variable under study (did this market survive to event day)?\n")
    con = _ro(PRED_DB)
    attempts = con.execute(
        "SELECT ticker, days_out, was_traded FROM analysis_attempts"
    ).fetchall()
    api = {
        ep.rsplit("/", 1)[-1]
        for (ep,) in con.execute(
            "SELECT DISTINCT endpoint FROM api_requests "
            "WHERE endpoint LIKE '/trade-api/v2/markets/KX%'"
        )
    }
    ph = {t for (t,) in con.execute("SELECT DISTINCT ticker FROM price_history")}
    con.close()

    cronlog: set[str] = set()
    if CRON_LOG_PATH.exists():
        import json

        with open(CRON_LOG_PATH, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        t = json.loads(line).get("ticker")
                    except Exception:
                        continue
                    if t:
                        cronlog.add(t)

    def cov(src, sub):
        return (sum(1 for t, *_ in sub if t in src) / len(sub)) if sub else float("nan")

    d1 = [r for r in attempts if (r[1] or 0) >= 1]
    d0 = [r for r in attempts if (r[1] or 0) == 0]
    tr = [r for r in attempts if r[2]]
    ut = [r for r in attempts if not r[2]]
    print(
        f"   {'source':<16}{'all':>8}{'d>=1':>8}{'d=0':>8}{'traded':>9}{'untraded':>10}"
    )
    for name, src in (
        ("api_requests", api),
        ("price_history", ph),
        ("cron.log", cronlog),
    ):
        print(
            f"   {name:<16}{cov(src, attempts):>7.0%}{cov(src, d1):>8.0%}"
            f"{cov(src, d0):>8.0%}{cov(src, tr):>9.0%}{cov(src, ut):>10.0%}"
        )
    print()
    print("   api_requests  -- the SCAN uses a LIST endpoint (/v2/markets) with no")
    print("     ticker. Per-ticker rows exist but come from position/settlement")
    print("     monitoring, so coverage tracks 'reached event day' almost exactly.")
    print("     Reconstructing first-scan horizon from it would drop the d>=1")
    print("     markets that stopped being scanned -- the population in question.")
    print("   price_history -- a position-monitoring table. Traded vs untraded")
    print("     coverage differs by an order of magnitude.")
    print("   cron.log      -- balanced on days_out, but it logs SIGNALS only, so")
    print("     most of the population is absent.")
    print("   => The proposed reconstruction is not possible with what is stored.\n")


def section_2_does_the_selection_matter(pop) -> None:
    print("2. DOES THE SELECTION CHANGE THE CALIBRATION WHERE IT IS APPLIED?")
    print("   The mechanism (established earlier) is analyze_trade's extreme_price")
    print("   gate: a market drifting to an extreme stops being analysed, freezing")
    print("   its row at d>=1. So partition the fit set on that same predicate.\n")
    ext = [r for r in pop if r["m"] < 0.10 or r["m"] > 0.90]
    mid = [r for r in pop if 0.10 <= r["m"] <= 0.90]
    print(
        f"   fit population n={len(pop)}   extreme-priced {len(ext)} "
        f"({len(ext) / len(pop):.0%})   mid-priced {len(mid)}"
    )
    fa, fm = fit_platt(pop), fit_platt(mid)
    print(
        f"   fit on ALL      a={fa[0]:+.4f} b={fa[1]:+.4f}   <- what production writes"
    )
    print(f"   fit on MID only a={fm[0]:+.4f} b={fm[1]:+.4f}")
    print("   IN-SAMPLE the two curves diverge sharply:")
    for p in (0.45, 0.55, 0.65):
        print(
            f"     p={p:.2f}  all={cal(p, *fa):.4f}  mid={cal(p, *fm):.4f}  "
            f"diff={cal(p, *fm) - cal(p, *fa):+.4f}"
        )
    print("   That number is the trap -- it is fitted and scored on the same rows.\n")

    print("   OUT-OF-SAMPLE, chronological, scored on held-out MID rows only")
    print("   (the tradeable domain the calibration is actually applied to):")
    print(f"   {'split':<8}{'n_test':>7}{'mid-only':>11}{'+extremes':>11}{'diff':>10}")
    for frac in (0.5, 0.6, 0.7, 0.8):
        cut = int(len(mid) * frac)
        tr, te = mid[:cut], mid[cut:]
        if len(te) < 15:
            continue
        fA, fB = fit_platt(tr), fit_platt(tr + ext)
        a, b = brier(te, *fA), brier(te, *fB)
        print(f"   {frac:<8.0%}{len(te):>7}{a:>11.5f}{b:>11.5f}{b - a:>+10.5f}")
    print()
    cut = int(len(mid) * 0.6)
    tr, te = mid[:cut], mid[cut:]
    fA, fB = fit_platt(tr), fit_platt(tr + ext)
    d = [
        (cal(r["p"], *fB) - r["y"]) ** 2 - (cal(r["p"], *fA) - r["y"]) ** 2 for r in te
    ]
    random.seed(11)
    boots = sorted(sum(random.choices(d, k=len(d))) / len(d) for _ in range(4000))
    print(f"   paired mean diff at the 60% split = {sum(d) / len(d):+.5f}")
    print(
        f"   95% CI [{boots[100]:+.5f}, {boots[3900]:+.5f}]   "
        f"P(including extremes HURTS) = {sum(1 for x in boots if x > 0) / len(boots):.3f}"
    )
    print(
        f"   raw uncalibrated {sum((r['p'] - r['y']) ** 2 for r in te) / len(te):.5f}   "
        f"market alone {sum((r['m'] - r['y']) ** 2 for r in te) / len(te):.5f}"
    )
    print()
    print("   => The selection is REAL and LARGE in the population, but including")
    print("      it does not measurably degrade the calibration on the tradeable")
    print("      domain. Underpowered: the held-out set is small, so this reads as")
    print("      'no detectable harm', NOT 'proven harmless'.")


def main() -> None:
    pop = load_fit_population()
    print(f"core d>=1 fit population: {len(pop)} rows (batch-93 measured {EXPECTED_N})")
    if len(pop) != EXPECTED_N:
        print("  NOTE: population has moved since batch-93. Growth is expected --")
        print("  this is a live-state question. A SHRINK would mean something")
        print("  rewrote analysis_attempts and is worth investigating first.")
    print()
    section_1_why_the_proposed_method_fails(pop)
    section_2_does_the_selection_matter(pop)


if __name__ == "__main__":
    main()
