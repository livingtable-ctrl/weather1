"""Pass 20 repro: param_sweep.py's PAPER_MIN_EDGE sweep values vs. its own
accepted range in load_swept_min_edge()/config.py.

Simulates realistic paper trades whose net_edge values sit in the actual
PAPER_MIN_EDGE operating range documented in config.py/tests
(walk_forward_params.json check: 0.03 <= opt <= 0.15; default 0.05;
tests/test_param_sweep_load.py uses 0.05-0.10 as example values).
"""
import random
import sys

sys.path.insert(0, r"C:\Users\thesa\claude kalshi\.claude\worktrees\reverent-lumiere-f79c1f")

from param_sweep import sweep_parameter, load_swept_min_edge  # noqa: E402

random.seed(42)

# Realistic PAPER_MIN_EDGE-scale trades: net_edge uniformly in [0.03, 0.16],
# win probability weakly correlated with edge (more edge -> slightly better
# win rate), matching how a real edge signal would behave.
trades = []
for i in range(500):
    edge = round(random.uniform(0.03, 0.16), 4)
    p_win = min(0.85, 0.45 + edge * 2.0)
    won = random.random() < p_win
    trades.append({"net_edge": edge, "won": won, "outcome": "yes" if won else "no"})

values = [0.15, 0.20, 0.25, 0.30, 0.35, 0.40]  # actual values used in param_sweep.run_sweep()
results = sweep_parameter("PAPER_MIN_EDGE", values, trades)
print("Sweep results (PAPER_MIN_EDGE values actually used in run_sweep()):")
for r in results:
    print(f"  value={r['value']:.2f}  trades={r['trades']}  win_rate={r['win_rate']}")

print()
print("Trades with net_edge >= 0.15 (only value in the swept list this trade pool can ever populate):",
      sum(1 for t in trades if t["net_edge"] >= 0.15))
print("Trades with net_edge >= 0.20:", sum(1 for t in trades if t["net_edge"] >= 0.20))

# What the "sensible" range [0.03, 0.15] sweep would look like instead:
sensible_values = [0.03, 0.05, 0.07, 0.09, 0.11, 0.13, 0.15]
sensible_results = sweep_parameter("PAPER_MIN_EDGE", sensible_values, trades)
print()
print("Sweep results if PAPER_MIN_EDGE were tested over its OWN documented range instead:")
for r in sensible_results:
    print(f"  value={r['value']:.2f}  trades={r['trades']}  win_rate={r['win_rate']}")
