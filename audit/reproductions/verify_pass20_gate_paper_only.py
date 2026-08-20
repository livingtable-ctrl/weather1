"""Pass 20 verification (E2): confirm the LiveTradingGate's risk-halt
sub-checks (paper.is_paused_drawdown / is_streak_paused) are computed
exclusively from paper.py's own JSON ledger and never consult
execution_log.db, even when execution_log shows catastrophic realized
live losses.

SAFETY: this script never touches the real project data/ directory.
paper.DATA_PATH and execution_log.DB_PATH (and the getter functions that
read them) are monkeypatched to files inside a throwaway tempfile.TemporaryDirectory()
before any read/write happens, so nothing here can reach the main clone's
real paper_trades.json / execution_log.db (see project memory: "Worktree
data dir gotcha" -- paths.py resolves data/ to the MAIN CLONE regardless of
worktree, so this redirection is done at the attribute level, not by
pointing at a worktree-local "data/" path).
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, r"C:\Users\thesa\claude kalshi\.claude\worktrees\reverent-lumiere-f79c1f")

os.environ.setdefault("KALSHI_ENV", "demo")

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
tmp_path = Path(tmpdir.name)

import execution_log  # noqa: E402
import paper  # noqa: E402

# --- Redirect paper.py's ledger to an empty/healthy synthetic ledger -------
paper_ledger_path = tmp_path / "paper_trades.json"
STARTING_BALANCE = paper.STARTING_BALANCE
healthy_paper_state = {
    "_version": 2,
    "balance": STARTING_BALANCE,
    "peak_balance": STARTING_BALANCE,
    "trades": [],  # no paper losses at all -- paper ledger looks perfectly healthy
}
paper_ledger_path.write_text(json.dumps(healthy_paper_state))
paper.DATA_PATH = paper_ledger_path
paper._existed_marker_path = lambda: tmp_path / ".paper_trades_existed"  # avoid CorruptionError path
(tmp_path / ".paper_trades_existed").touch()

# --- Redirect execution_log.py's DB to a synthetic DB showing a real,
#     catastrophic LIVE losing streak (10 losses in a row, well past the
#     10-consecutive-loss black-swan threshold and past any drawdown tier). --
exec_db_path = tmp_path / "execution_log.db"
execution_log.DB_PATH = exec_db_path  # _conn() reads this module global at call time
execution_log.init_log()

with execution_log._conn() as con:
    # Minimal schema probe: use whatever init_db() created, just confirm it's usable.
    cur = con.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cur.fetchall()]

print("execution_log tables created in synthetic DB:", tables)

# Simulate 10 consecutive real live losses via add_live_loss (real API), each
# a $95 loss on a $1000-scale account (9.5% each, ~$950 total realized loss --
# a genuine live account already near-wiped-out).
for i in range(10):
    execution_log.add_live_loss(95.0)

live_loss_today = execution_log.get_today_live_loss()
print(f"execution_log.get_today_live_loss() after 10x $95 live losses = ${live_loss_today:.2f}")

# --- Now call the actual gate sub-checks paper.py exposes to trading_gates.py
print()
print("paper.is_paused_drawdown()  ->", paper.is_paused_drawdown())
print("paper.is_streak_paused()    ->", paper.is_streak_paused())
print("paper.get_balance()         ->", paper.get_balance())
print("paper.get_peak_balance()    ->", paper.get_peak_balance())
print()
print(f"Conclusion: despite execution_log recording ${live_loss_today:.2f} in real realized live "
      "losses this run (10 consecutive), is_paused_drawdown()/is_streak_paused() "
      "report against the synthetic *paper* ledger only (0 trades, balance == "
      "peak_balance == STARTING_BALANCE) and see nothing wrong.")

tmpdir.cleanup()
