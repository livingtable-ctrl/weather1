"""
Pass 14 (Performance) repro: measure the real per-call cost of the two
operations that _log_shadow_predictions() (order_executor.py) repeats once
PER SHADOW TICKER per cron cycle, instead of once per cycle:

  1. paper.get_open_trades() -> paper._load() -- full JSON read + SHA-256
     checksum of the whole paper_trades.json ledger, on every call.
  2. tracker._conn() -- a brand-new sqlite3.connect() + 3 PRAGMA statements
     against predictions.db, on every call (opened/closed once per ticker
     because every call site in order_executor.py passes a single-item list:
     `_log_shadow_predictions([item], live=live)`).

This script benchmarks both operations directly against the REAL data files
in the main clone (read-only — no writes), to get real E3 timing evidence
instead of speculating "this must be slow". It does not import paper.py or
tracker.py (avoids triggering unrelated import-time side effects / other
worktree-vs-main-clone path resolution); it reproduces the exact operations
those functions perform on the same files.
"""
import hashlib
import json
import sqlite3
import time
from pathlib import Path

MAIN_CLONE = Path(r"C:\Users\thesa\claude kalshi")
PAPER_TRADES = MAIN_CLONE / "data" / "paper_trades.json"
PREDICTIONS_DB = MAIN_CLONE / "data" / "predictions.db"

print(f"paper_trades.json exists: {PAPER_TRADES.exists()}, size={PAPER_TRADES.stat().st_size if PAPER_TRADES.exists() else 'n/a'} bytes")
print(f"predictions.db exists: {PREDICTIONS_DB.exists()}, size={PREDICTIONS_DB.stat().st_size if PREDICTIONS_DB.exists() else 'n/a'} bytes")


def bench_load_paper_trades(n=30):
    times = []
    for _ in range(n):
        t0 = time.perf_counter()
        with open(PAPER_TRADES) as f:
            data = json.load(f)
        # mirror paper._validate_checksum's real cost: sha256 over the
        # canonical json body (approximated here with a stable dump of the
        # 'trades' field, which is the dominant cost driver regardless of
        # exact key set used by the real checksum body).
        body = json.dumps(data.get("trades", []), sort_keys=True).encode()
        _ = hashlib.sha256(body).hexdigest()
        t1 = time.perf_counter()
        times.append(t1 - t0)
    return times


def bench_tracker_conn(n=30):
    times = []
    for _ in range(n):
        t0 = time.perf_counter()
        con = sqlite3.connect(PREDICTIONS_DB)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
        con.execute("PRAGMA cache_size=10000")
        con.close()
        t1 = time.perf_counter()
        times.append(t1 - t0)
    return times


if __name__ == "__main__":
    if PAPER_TRADES.exists():
        t = bench_load_paper_trades()
        print(f"\npaper.get_open_trades()-equivalent (read+parse+sha256), n={len(t)}:")
        print(f"  mean={sum(t)/len(t)*1000:.3f}ms  min={min(t)*1000:.3f}ms  max={max(t)*1000:.3f}ms  total={sum(t)*1000:.1f}ms")
    else:
        print("paper_trades.json not found -- skipping")

    if PREDICTIONS_DB.exists():
        t = bench_tracker_conn()
        print(f"\ntracker._conn()-equivalent (sqlite3.connect + 3 PRAGMAs), n={len(t)}:")
        print(f"  mean={sum(t)/len(t)*1000:.3f}ms  min={min(t)*1000:.3f}ms  max={max(t)*1000:.3f}ms  total={sum(t)*1000:.1f}ms")
    else:
        print("predictions.db not found -- skipping")

    if PAPER_TRADES.exists() and PREDICTIONS_DB.exists():
        combined_per_call = (sum(bench_load_paper_trades(10)) + sum(bench_tracker_conn(10))) / 10
        print(f"\nCombined per-shadow-ticker overhead (both ops): ~{combined_per_call*1000:.3f}ms/call")
        for n_shadow in (5, 15, 30, 50):
            print(f"  projected added time for {n_shadow} shadow tickers in one cron cycle: {combined_per_call*n_shadow*1000:.1f}ms")
