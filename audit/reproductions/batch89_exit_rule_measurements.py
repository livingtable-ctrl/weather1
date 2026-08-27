"""Reproduce every measured number in batch-89's stop-loss / exit-rule entry.

Run:  python audit/reproductions/batch89_exit_rule_measurements.py

WHY THIS EXISTS: the backlog entry it supports tells future sessions NOT to
re-analyse the 195-trade set (~20 rule variants have already been tried on it,
so anything further found there is forking paths). That instruction is only
safe if the numbers already claimed are re-derivable. Without this script a
reader gets assertions and no way to check them -- which is exactly the
position that let a `between` measurement stand for a day while it was
actually measuring deleted code.

ISOLATION, deliberately different from most of audit/reproductions/:
  * The repo root is derived from THIS FILE's location, never hardcoded. 17
    of the existing scripts here open with a sys.path.insert pointing at a
    worktree that no longer exists; see backlog.txt's own entry about it.
  * Both databases are opened through a `file:...?mode=ro` URI, so the script
    CANNOT write to production data even by mistake.
  * tracker/ml_bias are deliberately NOT imported: importing them runs
    init_db(), which writes. Only `utils.kalshi_taker_fee` is imported, and
    only because using the production fee function is the point.

METHOD NOTES, each of which changed a result during the original work:
  * price_history.yes_bid_close/yes_ask_close are in DOLLARS (0-1), NOT
    cents. A first pass divided by 100 and reported the opposite conclusion.
  * A zero on either side is an EMPTY BOOK, not a free price. Rows require
    both quotes > 0 AND volume > 0.
  * outcome='early_exit' trades are excluded: they never reached settlement,
    so "what would a stop have done vs what happened" is malformed for them.
  * The real Kalshi taker fee is charged on the hypothetical exit. Omitting
    it flatters every exit rule.
  * price_history reaches only ~48h before close, so a position entered
    earlier has unobserved early life.
"""

from __future__ import annotations

import datetime as dt
import json
import random
import sqlite3
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

# data/ is resolved by paths.py, NOT by joining onto this file's location:
# in a git worktree the code lives under .claude/worktrees/<name>/ while
# paths.py deliberately resolves data/ back to the MAIN clone. Deriving it
# from __file__ finds nothing and the script dies on connect.
from paths import DATA_DIR, PAPER_TRADES_PATH  # noqa: E402
from utils import kalshi_taker_fee  # noqa: E402

PRED_DB = DATA_DIR / "predictions.db"
TRADES = PAPER_TRADES_PATH
GATE_HOURS = 24.0  # EXIT_SETTLEMENT_GATE_HOURS


def _ro(path: Path) -> sqlite3.Connection:
    """Read-only connection: the script must not be able to write production."""
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)


# The population is PINNED to what batch-89 measured. Without this the script
# silently measures a moving target: paper_trades.json keeps accruing
# settlements, so "the last 60" means different trades every week and "195
# settled" becomes 250. Re-running in October would then disagree with the
# backlog entry for a reason having nothing to do with whether the finding
# held -- which is worse than no repro script, because it looks like a
# refutation. Pass --live to score the CURRENT population instead: a useful
# question, but a different one from reproduction.
AS_OF = "2026-08-27"
EXPECTED_N = 195


def load(as_of: str | None = AS_OF):
    con = _ro(PRED_DB)
    trades = [
        t
        for t in json.loads(TRADES.read_text())["trades"]
        if t.get("settled")
        and t.get("pnl") is not None
        and t.get("close_time")
        and t.get("outcome") != "early_exit"
        and (as_of is None or (t.get("settled_at") or "") < as_of)
    ]
    trades.sort(key=lambda t: t.get("settled_at") or "")
    paths = {
        t["ticker"]: con.execute(
            "select end_period_ts, yes_bid_close, yes_ask_close from price_history "
            "where ticker=? and yes_bid_close>0 and yes_ask_close>0 and volume>0 "
            "order by end_period_ts",
            (t["ticker"],),
        ).fetchall()
        for t in trades
    }
    con.close()
    return trades, paths


def walk(t, paths, rows=None):
    """(hours_to_close, realizable_price, unrealized_pnl), chronological."""
    close = dt.datetime.fromisoformat(t["close_time"].replace("Z", "+00:00"))
    ep, qty, side = t.get("entry_price") or 0, t.get("quantity") or 0, t.get("side")
    for ts, bid, ask in rows if rows is not None else paths.get(t["ticker"], []):
        hrs = (close - dt.datetime.fromtimestamp(ts, dt.UTC)).total_seconds() / 3600
        px = bid if side == "yes" else (1.0 - ask)
        yield hrs, px, (px - ep) * qty


def fixed_stop(t, paths, loss_frac, lo=GATE_HOURS, hi=1e9, rows=None):
    cost, qty = t.get("cost") or 0, t.get("quantity") or 0
    if not cost:
        return None
    for hrs, px, pnl in walk(t, paths, rows):
        if not (lo <= hrs < hi):
            continue
        if pnl < -(cost * loss_frac):
            return (pnl - kalshi_taker_fee(qty, px)) - t["pnl"]
    return None


def ratchet(t, paths, giveback, trigger=0.20, rows=None):
    cost, qty = t.get("cost") or 0, t.get("quantity") or 0
    if not cost:
        return None
    peak = 0.0
    for hrs, px, pnl in walk(t, paths, rows):
        peak = max(peak, pnl)
        if peak < cost * trigger or hrs < GATE_HOURS:
            continue
        if pnl <= peak * (1 - giveback):
            return (pnl - kalshi_taker_fee(qty, px)) - t["pnl"]
    return None


def time_tightening(t, paths, rows=None):
    cost, qty = t.get("cost") or 0, t.get("quantity") or 0
    if not cost:
        return None
    peak = 0.0
    for hrs, px, pnl in walk(t, paths, rows):
        peak = max(peak, pnl)
        if peak < cost * 0.20 or hrs < GATE_HOURS:
            continue
        if pnl <= peak * (0.40 if hrs > 36 else 0.75):
            return (pnl - kalshi_taker_fee(qty, px)) - t["pnl"]
    return None


def summarise(deltas, seed=17):
    deltas = [d for d in deltas if d is not None]
    if not deltas:
        return None
    random.seed(seed)
    boots = sorted(sum(random.choices(deltas, k=len(deltas))) for _ in range(3000))
    return {
        "n": len(deltas),
        "net": sum(deltas),
        "mean": statistics.mean(deltas),
        "lo": boots[75],
        "hi": boots[2925],
        "p_pos": sum(1 for b in boots if b > 0) / len(boots),
    }


def line(label, s):
    if s is None:
        print(f"  {label:<38} n=0 -- never fires")
        return
    print(
        f"  {label:<38} n={s['n']:<4} net {s['net']:+9.2f} mean {s['mean']:+6.2f} "
        f"95% CI [{s['lo']:+8.2f},{s['hi']:+8.2f}] P(>0)={s['p_pos']:.3f}"
    )


def main() -> None:
    live = "--live" in sys.argv
    trades, paths = load(None if live else AS_OF)
    last60 = trades[-60:]
    scope = "CURRENT population (--live)" if live else f"population as of {AS_OF}"
    print(f"{scope}: {len(trades)} settled trades (early_exit excluded), "
          f"{sum(1 for t in trades if paths.get(t['ticker']))} with a two-sided book")
    if not live and len(trades) != EXPECTED_N:
        print(
            f"  !! EXPECTED {EXPECTED_N} TRADES, GOT {len(trades)} -- the PINNED\n"
            "  !! population changed, so nothing below will match the backlog.\n"
            "  !! Something rewrote history in paper_trades.json (a re-settlement,\n"
            "  !! a pnl correction, a restore). Investigate THAT before trusting\n"
            "  !! either set of figures."
        )
    print()

    print("1. FIXED STOP-LOSS THRESHOLD SWEEP (backlog: negative at every setting)")
    for frac in (0.25, 0.40, 0.50, 0.60, 0.75, 0.90):
        tag = "  <- was live" if frac == 0.50 else ""
        line(f"all: loss > {int(frac*100)}% of cost{tag}",
             summarise([fixed_stop(t, paths, frac) for t in trades]))
    for frac in (0.25, 0.50, 0.90):
        line(f"last60: loss > {int(frac*100)}% of cost",
             summarise([fixed_stop(t, paths, frac) for t in last60]))

    print("\n2. LOWERING THE 24h SETTLEMENT GATE -- INCREMENTAL effect")
    print("   INCREMENTAL: a trade whose stop already triggers at >=24h exits")
    print("   under the CURRENT policy and can never reach the sub-24h window,")
    print("   so counting it here double-counts it against section 1. Excluded.")

    def incremental(sub, gate):
        return [
            fixed_stop(t, paths, 0.50, lo=gate, hi=GATE_HOURS)
            for t in sub
            if fixed_stop(t, paths, 0.50) is None
        ]

    for gate in (18.0, 12.0, 8.0, 0.0):
        line(f"all: gate lowered to {gate:>4.0f}h", summarise(incremental(trades, gate)))
    line("last60: gate removed entirely", summarise(incremental(last60, 0.0)))

    print("\n3. OUT-OF-SAMPLE SPLIT (choose on the earlier trades, score on the later)")
    cut = int(len(trades) * 0.6)
    for name, fn in (
        ("ratchet keep-70%-of-peak", lambda t: ratchet(t, paths, 0.30)),
        ("time-tightening", lambda t: time_tightening(t, paths)),
    ):
        line(f"{name} TRAIN", summarise([fn(t) for t in trades[:cut]]))
        line(f"{name} TEST", summarise([fn(t) for t in trades[cut:]]))

    print("\n4. SHUFFLED-PATH NULL TEST -- the check that killed the ratchet")
    print("   Give each trade a RANDOM other trade's price path. A rule whose")
    print("   gain is structural rather than path-reading scores positive anyway.")
    for name, fn in (
        ("ratchet keep-70%-of-peak", lambda t, rows: ratchet(t, paths, 0.30, rows=rows)),
        ("time-tightening", lambda t, rows: time_tightening(t, paths, rows=rows)),
    ):
        random.seed(99)
        nulls = []
        for _ in range(200):
            # Per-TRADE, not per-ticker: keying off paths.keys() truncates
            # zip() whenever two trades share a ticker, biasing the null low
            # and therefore p low. Zero duplicates in the pinned population,
            # so latent -- but this is the null test that killed the ratchet,
            # so it must not be able to drift.
            keys = [t["ticker"] for t in trades]
            random.shuffle(keys)
            nulls.append(
                sum(
                    d
                    for d in (fn(t, paths[k]) for t, k in zip(trades, keys))
                    if d is not None
                )
            )
        real = sum(d for d in (fn(t, None) for t in trades) if d is not None)
        nulls.sort()
        p = sum(1 for x in nulls if x >= real) / len(nulls)
        print(
            f"  {name:<28} real {real:+9.2f}  null median {statistics.median(nulls):+9.2f}"
            f"  empirical p={p:.3f}"
        )

    print("\nPositive net = the rule BEAT doing nothing. Negative = it cost money.")
    print("A rule whose null median is far above zero is not reading the path.")


if __name__ == "__main__":
    main()
