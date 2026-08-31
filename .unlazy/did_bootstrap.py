"""Bootstrap the surviving claim, stratified.

The pooled AUC drop is confounded by condition-type mix. What survives is a
DIFFERENCE IN DIFFERENCES: within a stratum, the market's AUC rose while the
model's fell. Test that directly, without the parametric Hanley-McNeil SE.

  statistic = (model_MayJun - model_JulAug) - (market_MayJun - market_JulAug)

Positive means the model deteriorated relative to the market. Resampled by
market (ticker) so rows of one settlement are not treated as independent.
READ-ONLY.
"""

import pathlib
import random
import sqlite3
import statistics
from collections import defaultdict

DB = pathlib.Path(r"C:\Users\thesa\claude kalshi\data\predictions.db")


def auc(pairs):
    pos = [p for p, y in pairs if y == 1]
    neg = [p for p, y in pairs if y == 0]
    if not pos or not neg:
        return None
    return sum(1.0 if a > b else 0.5 if a == b else 0.0 for a in pos for b in neg) / (
        len(pos) * len(neg)
    )


con = sqlite3.connect("file:" + DB.as_posix() + "?mode=ro", uri=True)
rows = con.execute(
    """SELECT strftime('%Y-%m', p.predicted_at), p.our_prob, p.market_prob,
              o.settled_yes, p.condition_type, p.ticker
       FROM predictions p JOIN outcomes_valid o ON o.ticker = p.ticker
       WHERE o.settled_yes IN (0,1) AND p.our_prob IS NOT NULL
         AND p.market_prob IS NOT NULL AND p.condition_type IN ('above','below')
         AND (p.ticker LIKE 'KXHIGH%' OR p.ticker LIKE 'KXLOWT%')"""
).fetchall()
con.close()


def per(m):
    return "MayJun" if m in ("2026-05", "2026-06") else "JulAug"


# one record per row, grouped by ticker for the cluster bootstrap
by_ticker = defaultdict(list)
for m, op, mp, y, ct, tk in rows:
    by_ticker[tk].append((per(m), ct, op, mp, float(y)))
tickers = list(by_ticker)
print(f"rows {len(rows)}  tickers {len(tickers)}  (above+below only)")


def did(sample_tickers):
    """Difference-in-differences, pooled over the above/below strata."""
    g = defaultdict(list)
    for tk in sample_tickers:
        for p_, ct, op, mp, y in by_ticker[tk]:
            g[(p_, ct, "model")].append((op, y))
            g[(p_, ct, "market")].append((mp, y))
    out = []
    for ct in ("above", "below"):
        vals = {}
        for p_ in ("MayJun", "JulAug"):
            for who in ("model", "market"):
                a = auc(g[(p_, ct, who)])
                if a is None:
                    return None
                vals[(p_, who)] = a
        out.append(
            (vals[("MayJun", "model")] - vals[("JulAug", "model")])
            - (vals[("MayJun", "market")] - vals[("JulAug", "market")])
        )
    return statistics.fmean(out)


obs = did(tickers)
print(f"observed DiD = {obs:+.4f}  (positive = model deteriorated vs market)")

rng = random.Random(20260830)
boot = []
for _ in range(2000):
    s = [rng.choice(tickers) for _ in tickers]
    v = did(s)
    if v is not None:
        boot.append(v)
boot.sort()
lo, hi = boot[int(0.025 * len(boot))], boot[int(0.975 * len(boot))]
share_le0 = sum(1 for b in boot if b <= 0) / len(boot)
print(f"cluster bootstrap, {len(boot)} resamples")
print(f"  95% CI [{lo:+.4f}, {hi:+.4f}]")
print(
    f"  share of resamples <= 0: {share_le0:.3f}   (two-sided p ~ {2 * min(share_le0, 1 - share_le0):.3f})"
)
print()
print(
    "VERDICT:",
    "CI excludes 0 -- divergence survives"
    if lo > 0
    else "CI INCLUDES 0 -- divergence NOT established",
)
