"""Reproduce step 2 of backlog.txt's gfs_seamless entry: paired member scores
on Brier, and the leave-one-out debiasing that dissolves the "2x MAE" figure.

Run:  python -m audit.reproductions.gfs_step2_paired_brier   (from the repo root)

WHAT THIS SETTLES. The entry recorded gfs_seamless at ~2x its peers' MAE on
`max` and asked (step 2) for a paired re-measurement on BRIER at a defensible
n before any reweighting. This script answers that, and shows the raw MAE gap
is an artifact of measuring a column the blend never prices from:

  * ensemble_member_scores.predicted_temp is the RAW member mean, written by
    paper._score_ensemble_members from analyze_trade's model_forecast_means
    <- _get_consensus_probs <- _model_prob_and_mean. No bias correction.
  * get_ensemble_temps subtracts _model_bias() from every member before the
    blend (`temps = [t - model_bias for t in temps]`). So the pipeline
    already removes the offset that dominates gfs's raw MAE.
  * The blend does, however, DERIVE things from that raw column -- both the
    bias correction above and the weights (_weights_from_mae ->
    get_member_accuracy). See the backlog entry "LIVE BLEND WEIGHTS ARE FIT
    ON RAW MAE WHILE THE BLEND ITSELF SUBTRACTS THE SAME BIAS".

Section 1  per-model signed bias by var and month  (the offset)
Section 2  paired MAE, raw vs leave-one-out debiased  (the dissolution)
Section 3  paired Brier  (the metric the entry requires)
Section 4  icon-vs-gfs over the full history  (it is drift, not a property)

ISOLATION:
  * isolate(allow_real_data=True) arms tests/prod_data_guard before any repo
    import, per audit/reproductions/README.md. This script MUST read the real
    predictions.db -- that is the measurement -- so it opts into real data
    rather than sandboxing it, and the guard reports any write attempt.
  * predictions.db is opened `file:...?mode=ro`, so this cannot write to it.
  * Only NON_MODEL_SCORE_KEYS is imported from tracker (a module constant;
    tracker has no module-level init_db()). No tracker READ HELPER is called
    -- every one of them starts with init_db(), which opens the DB read-write
    and can migrate it.
  * DATA_DIR comes from paths.py, not from __file__: in a worktree the code
    lives under .claude/worktrees/<name>/ while paths resolves data/ back to
    the MAIN clone.
  * THIS SCRIPT IS NOT WRITE-FREE, and the guard says so on every run. Merely
    importing paths.py runs materialize_missing_seeds() (paths.py:315), which
    opens and then unlinks nine `.<name>.json.seed-<pid>.tmp` files inside the
    real data/. tracker imports paths, so there is no import order that avoids
    it. Nothing is clobbered -- the os.link into place fails when the real
    file already exists -- and predictions.db itself is mode=ro. The guard
    reporting those 27 mutations at exit is CORRECT and expected output, not a
    failure; treat any OTHER path in that report as a real finding.

METHOD NOTES:
  * A "cell" is (city, target_date, var), matching the entry's own pairing.
    Only cells where EVERY compared model is present are used, so every
    comparison is like-for-like.
  * THE CORPUS IS SELECTED. ensemble_member_scores has exactly one production
    writer -- paper._score_ensemble_members, which runs at SETTLEMENT OF A
    PLACED PAPER TRADE. Every row therefore describes a market the bot's edge
    gates chose to trade, and those gates read these same models. Within-cell
    pairing is fairly robust to it; nothing here is a claim about all markets.
  * Debiasing is LEAVE-ONE-OUT (each row corrected by the bias computed from
    all OTHER rows of that model/var). In-sample debiasing would flatter the
    biased member by construction.
  * WHAT THE SIGN-FLIP P DOES AND DOES NOT REPAIR. A t on LOO-debiased errors
    is not a textbook paired t, for two separate reasons, and the permutation
    only covers one. It is distribution-free, so it removes the small-n
    normality assumption. It does NOT remove the dependence LOO itself
    introduces: every row's correction is a function of all the other rows, so
    the differences are not independent and sign-symmetric under the null, and
    the permutation distribution is not the exact randomization distribution
    either. Neither statistic accounts for that. Treat both as indicative.
  * All four permutations share seed=0, i.e. the same 20,000 sign patterns.
    Each is individually valid; they are not independent of each other.
  * THE LOO POOLS ARE NOT THE SAME SIZE ACROSS MODELS. Each model's correction
    is fit over its own in-window rows, and at var=min that is 36 rows for gfs
    and icon against 34 for aifs, while only 34 CELLS are compared. So the
    three corrections are estimated with slightly different precision.
  * LOO debiasing is an ESTIMATE of what the blend does, not a replay of it:
    _model_bias applies a 60-day rolling logged_at window under its own
    city/global sample floors, which is not identical to a LOO fit over these
    cells. Section 1 buckets by target_date MONTH, which is a third slicing --
    the numbers there will not equal get_member_bias()'s.
  * NOT date-pinned, deliberately: re-run it as n grows. EXPECTED_* below
    record the shape at first run so a later reader can tell "grown" from
    "changed".
"""

from audit.reproductions._isolate import isolate

isolate(allow_real_data=True, label="gfs_step2")

import random  # noqa: E402
import sqlite3  # noqa: E402
import statistics as st  # noqa: E402
from collections import defaultdict  # noqa: E402

from paths import DATA_DIR  # noqa: E402
from tracker import NON_MODEL_SCORE_KEYS  # noqa: E402

DB = DATA_DIR / "predictions.db"
NON_MODEL_KEYS = tuple(sorted(NON_MODEL_SCORE_KEYS))
LIVE = ["icon_seamless", "gfs_seamless", "ecmwf_aifs025_ensemble"]
WINDOW_DAYS = 60

# Shape at first run, 2026-09-01T23:44Z. Not assertions -- a divergence means
# the corpus moved, which is expected and is the point of re-running.
EXPECTED_ROWS_ALL = 473
EXPECTED_CELLS = {"max": 26, "min": 34}


def _rows(con, window_only):
    placeholders = ",".join("?" * len(NON_MODEL_KEYS))
    sql = f"""
        SELECT model, city, target_date, var, predicted_temp, actual_temp, brier
        FROM ensemble_member_scores
        WHERE model NOT IN ({placeholders})
          AND var IS NOT NULL
          AND predicted_temp IS NOT NULL
          AND actual_temp IS NOT NULL
    """
    params = list(NON_MODEL_KEYS)
    if window_only:
        sql += " AND logged_at >= datetime('now', ? || ' days')"
        params.append(f"-{WINDOW_DAYS}")
    return con.execute(sql, params).fetchall()


def _cells(rows) -> dict:
    out: defaultdict = defaultdict(dict)
    for r in rows:
        out[(r["city"], r["target_date"], r["var"])][r["model"]] = r
    return out


def _paired_t(a, b):
    d = [x - y for x, y in zip(a, b)]
    mu = sum(d) / len(d)
    sd = st.stdev(d) if len(d) > 1 else 0.0
    return mu, (mu / (sd / len(d) ** 0.5) if sd else float("nan"))


def _signflip_p(a, b, draws=20000, seed=0):
    """Two-sided sign-flip permutation p for a paired difference.

    The t-statistics on LOO-debiased errors are not textbook paired t's, so
    every debiased comparison is reported with this alongside it.
    """
    d = [x - y for x, y in zip(a, b)]
    obs = abs(sum(d) / len(d))
    rng = random.Random(seed)
    hits = sum(
        1
        for _ in range(draws)
        if abs(sum(v if rng.random() < 0.5 else -v for v in d) / len(d)) >= obs
    )
    return (hits + 1) / (draws + 1)


def main():
    con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    win = _rows(con, window_only=True)
    allr = _rows(con, window_only=False)

    print(f"DB: {DB}")
    print(f"as of: {con.execute("SELECT datetime('now')").fetchone()[0]} UTC")
    print(
        f"{len(win)} model rows in the last {WINDOW_DAYS}d; "
        f"{len(allr)} all-time (first run: {EXPECTED_ROWS_ALL})\n"
    )

    # 1 -- the signed offset, bucketed by target_date month
    print("1. SIGNED BIAS (predicted - actual), degF, by target_date MONTH")
    print("   NB: _model_bias uses a 60d logged_at window, NOT these buckets --")
    print("   these will not equal tracker.get_member_bias()'s numbers.")
    pools = defaultdict(list)
    for r in allr:
        pools[(r["model"], r["var"], r["target_date"][:7])].append(
            r["predicted_temp"] - r["actual_temp"]
        )
    print(f"   {'model':<28} {'var':<4} {'month':<8} {'n':>4} {'bias':>7} {'sd':>6}")
    for k in sorted(pools):
        v = pools[k]
        sd = st.stdev(v) if len(v) > 1 else 0.0
        print(
            f"   {k[0]:<28} {k[1]:<4} {k[2]:<8} {len(v):>4} "
            f"{sum(v) / len(v):>+7.2f} {sd:>6.2f}"
        )

    # 2 -- paired MAE, raw vs leave-one-out debiased
    loo_pool = defaultdict(list)
    for r in win:
        loo_pool[(r["model"], r["var"])].append(r["predicted_temp"] - r["actual_temp"])

    def loo(model, var, err):
        p = loo_pool[(model, var)]
        return (sum(p) - err) / (len(p) - 1) if len(p) > 1 else 0.0

    print(f"\n2. PAIRED MAE, RAW vs LEAVE-ONE-OUT DEBIASED ({WINDOW_DAYS}d window)")
    cells = _cells(win)
    for var in ("max", "min"):
        sub = [v for k, v in cells.items() if k[2] == var and all(m in v for m in LIVE)]
        if not sub:
            continue
        raw: dict = {}
        deb: dict = {}
        for m in LIVE:
            errs = [v[m]["predicted_temp"] - v[m]["actual_temp"] for v in sub]
            raw[m] = [abs(e) for e in errs]
            deb[m] = [abs(e - loo(m, var, e)) for e in errs]
        print(f"   var={var}  n={len(sub)}  (first run: {EXPECTED_CELLS[var]})")
        print(f"     {'model':<28} {'raw':>8} {'debiased':>10}")
        for m in sorted(LIVE, key=lambda m: sum(deb[m]) / len(deb[m])):
            print(
                f"     {m:<28} {sum(raw[m]) / len(raw[m]):>8.3f} "
                f"{sum(deb[m]) / len(deb[m]):>10.3f}"
            )
        for p in [m for m in LIVE if m != "gfs_seamless"]:
            mr, tr = _paired_t(raw["gfs_seamless"], raw[p])
            md, td = _paired_t(deb["gfs_seamless"], deb[p])
            pv = _signflip_p(deb["gfs_seamless"], deb[p])
            print(
                f"       gfs - {p:<24} raw {mr:+.3f} (t={tr:+.2f})   "
                f"debiased {md:+.3f} (t={td:+.2f}, signflip p={pv:.3f})"
            )

    # 3 -- paired Brier, the metric the entry requires.
    # Same 60d window as section 2 so the two sections describe the same cells;
    # without it a brier-bearing row aging past the window would silently make
    # them diverge.
    print(f"\n3. PAIRED BRIER -- the metric step 2 requires ({WINDOW_DAYS}d window)")
    bcells = _cells([r for r in win if r["brier"] is not None])
    for var in ("max", "min"):
        sub = [
            v for k, v in bcells.items() if k[2] == var and all(m in v for m in LIVE)
        ]
        if not sub:
            continue
        sc = {m: [v[m]["brier"] for v in sub] for m in LIVE}
        print(f"   var={var}  n={len(sub)}   (batch-81's single-signal floor is 112)")
        for m in sorted(LIVE, key=lambda m: sum(sc[m]) / len(sc[m])):
            print(f"     {m:<28} {sum(sc[m]) / len(sc[m]):.4f}")
        for p in [m for m in LIVE if m != "gfs_seamless"]:
            mu, t = _paired_t(sc["gfs_seamless"], sc[p])
            print(f"       gfs - {p:<24} {mu:+.4f}  t={t:+.2f}")

    # 4 -- the pair that reaches back before August. Bucket labels name the
    # filter exactly: "pre-Jul" is target_date < 2026-07, "Aug+" is >= 2026-08.
    print("\n4. icon vs gfs OVER FULL HISTORY -- the only pair with pre-August rows")
    pair = ["icon_seamless", "gfs_seamless"]
    acells = _cells(allr)
    for var in ("max", "min"):
        by_key = {
            k: v for k, v in acells.items() if k[2] == var and all(m in v for m in pair)
        }
        if not by_key:
            continue
        for lab, keys in (
            ("full", list(by_key)),
            ("pre-Jul", [k for k in by_key if k[1] < "2026-07"]),
            ("Aug+", [k for k in by_key if k[1] >= "2026-08"]),
        ):
            if len(keys) < 3:
                continue
            g = [
                abs(
                    by_key[k]["gfs_seamless"]["predicted_temp"]
                    - by_key[k]["gfs_seamless"]["actual_temp"]
                )
                for k in keys
            ]
            i = [
                abs(
                    by_key[k]["icon_seamless"]["predicted_temp"]
                    - by_key[k]["icon_seamless"]["actual_temp"]
                )
                for k in keys
            ]
            mu, t = _paired_t(g, i)
            print(
                f"   var={var:<4} {lab:<8} n={len(keys):<4} gfs {sum(g) / len(g):.3f}  "
                f"icon {sum(i) / len(i):.3f}  ratio {sum(g) / sum(i):.2f}x  "
                f"diff {mu:+.3f} t={t:+.2f}"
            )

    con.close()


if __name__ == "__main__":
    main()
