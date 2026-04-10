"""
Monte Carlo simulation for paper trading portfolio.
Simulates N random outcome scenarios given current open positions.
"""

from __future__ import annotations

import random


def simulate_portfolio(
    open_trades: list[dict],
    n_simulations: int = 1000,
    analysis_map: dict | None = None,  # ticker -> analyze_trade result
) -> dict:
    """
    For each simulation: randomly resolve each open trade as win/loss
    using the model's forecast_prob as the win probability.

    Returns:
      {
        "median_pnl": float,
        "p10_pnl": float,   # 10th percentile (bad scenario)
        "p90_pnl": float,   # 90th percentile (good scenario)
        "prob_positive": float,  # fraction of sims with positive P&L
        "prob_ruin": float,      # fraction of sims losing >20% of current balance
        "current_balance": float,
        "n_simulations": int,
      }
    """
    from paper import get_balance

    current_balance = get_balance()

    if not open_trades:
        return {
            "median_pnl": 0.0,
            "p10_pnl": 0.0,
            "p90_pnl": 0.0,
            "prob_positive": 0.5,
            "prob_ruin": 0.0,
            "current_balance": current_balance,
            "n_simulations": n_simulations,
        }

    from utils import KALSHI_FEE_RATE

    # Build per-trade win probability
    trade_params: list[dict] = []
    for t in open_trades:
        ticker = t.get("ticker", "")
        side = t.get("side", "yes")
        entry_price = t.get("entry_price", 0.5)
        cost = t.get("cost", 0.0)
        qty = t.get("quantity", 1)

        # Win probability: prefer analysis_map, fall back to entry_prob, then 0.5
        if analysis_map and ticker in analysis_map:
            ana = analysis_map[ticker]
            forecast_prob = ana.get("forecast_prob", 0.5) if ana else 0.5
            win_prob = forecast_prob if side == "yes" else 1 - forecast_prob
        else:
            entry_prob = t.get("entry_prob")
            win_prob = entry_prob if entry_prob is not None else 0.5

        win_prob = max(0.0, min(1.0, win_prob))

        # If we win: payout per contract = 1 - fee on winnings
        winnings_per = 1.0 - entry_price
        net_payout_per = 1.0 - winnings_per * KALSHI_FEE_RATE
        win_pnl = qty * net_payout_per - cost
        loss_pnl = -cost

        trade_params.append(
            {
                "win_prob": win_prob,
                "win_pnl": win_pnl,
                "loss_pnl": loss_pnl,
            }
        )

    ruin_threshold = current_balance * 0.20  # losing >20% of current balance

    sim_pnls: list[float] = []
    rng = random.Random()
    for _ in range(n_simulations):
        total_pnl = 0.0
        for tp in trade_params:
            if rng.random() < tp["win_prob"]:
                total_pnl += tp["win_pnl"]
            else:
                total_pnl += tp["loss_pnl"]
        sim_pnls.append(total_pnl)

    sim_pnls.sort()
    n = len(sim_pnls)
    median_pnl = sim_pnls[n // 2]
    p10_pnl = sim_pnls[max(0, int(n * 0.10))]
    p90_pnl = sim_pnls[min(n - 1, int(n * 0.90))]
    prob_positive = sum(1 for p in sim_pnls if p > 0) / n
    prob_ruin = sum(1 for p in sim_pnls if p < -ruin_threshold) / n

    return {
        "median_pnl": round(median_pnl, 2),
        "p10_pnl": round(p10_pnl, 2),
        "p90_pnl": round(p90_pnl, 2),
        "prob_positive": round(prob_positive, 4),
        "prob_ruin": round(prob_ruin, 4),
        "current_balance": round(current_balance, 2),
        "n_simulations": n_simulations,
    }
