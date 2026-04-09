"""
Paper trading ledger — simulates trades without using real money.
Stored in data/paper_trades.json. Tracks:
  - Entry: ticker, side, quantity, entry_price, entry_prob
  - Exit/settlement: outcome, P&L
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

DATA_PATH = Path(__file__).parent / "data" / "paper_trades.json"
DATA_PATH.parent.mkdir(exist_ok=True)

STARTING_BALANCE = 1000.0  # default paper bankroll in dollars


def _load() -> dict:
    if DATA_PATH.exists():
        with open(DATA_PATH) as f:
            return json.load(f)
    return {"balance": STARTING_BALANCE, "trades": []}


def _save(data: dict) -> None:
    with open(DATA_PATH, "w") as f:
        json.dump(data, f, indent=2)


def get_balance() -> float:
    return _load()["balance"]


def kelly_bet_dollars(kelly_fraction: float) -> float:
    """
    Return the dollar amount to bet based on Kelly fraction × current balance.
    This compounds automatically — as your balance grows, bet sizes grow too.
    Floors at $0 and caps at 25% of balance as a safety limit.
    """
    balance = get_balance()
    fraction = max(0.0, min(kelly_fraction, 0.25))  # hard cap at 25%
    return round(balance * fraction, 2)


def kelly_quantity(kelly_fraction: float, price: float) -> int:
    """
    Convert a Kelly dollar amount to a quantity (contracts) at a given price.
    Returns at least 1 if there is any positive edge and balance allows.
    """
    if price <= 0:
        return 0
    dollars = kelly_bet_dollars(kelly_fraction)
    qty = int(dollars / price)
    return max(qty, 1) if dollars > 0 else 0


def place_paper_order(
    ticker: str,
    side: str,  # "yes" or "no"
    quantity: int,
    entry_price: float,
    entry_prob: float | None = None,
    net_edge: float | None = None,
) -> dict:
    """
    Place a paper trade. Deducts quantity * entry_price from balance.
    Returns the trade record.
    """
    data = _load()
    cost = quantity * entry_price

    if data["balance"] < cost:
        raise ValueError(
            f"Insufficient paper balance (${data['balance']:.2f}) "
            f"for this order (${cost:.2f})."
        )

    trade = {
        "id": len(data["trades"]) + 1,
        "ticker": ticker,
        "side": side,
        "quantity": quantity,
        "entry_price": entry_price,
        "entry_prob": entry_prob,
        "net_edge": net_edge,
        "cost": cost,
        "entered_at": datetime.utcnow().isoformat(),
        "settled": False,
        "outcome": None,
        "pnl": None,
    }

    data["balance"] -= cost
    data["trades"].append(trade)
    _save(data)
    return trade


def settle_paper_trade(trade_id: int, outcome_yes: bool) -> dict:
    """
    Record settlement for a paper trade. YES wins if outcome_yes=True.
    Returns the updated trade.
    """
    data = _load()
    for t in data["trades"]:
        if t["id"] == trade_id and not t["settled"]:
            qty = t["quantity"]
            side = t["side"]
            cost = t["cost"]
            won = (side == "yes" and outcome_yes) or (side == "no" and not outcome_yes)
            payout = qty * 1.0 * (1 - 0.07) if won else 0.0  # 7% Kalshi fee on winnings
            pnl = payout - cost

            t["settled"] = True
            t["outcome"] = "yes" if outcome_yes else "no"
            t["pnl"] = round(pnl, 4)
            data["balance"] += payout
            _save(data)
            return t
    raise ValueError(f"Trade {trade_id} not found or already settled.")


def get_open_trades() -> list[dict]:
    return [t for t in _load()["trades"] if not t["settled"]]


def get_all_trades() -> list[dict]:
    return _load()["trades"]


def get_performance() -> dict:
    """Summary stats across all settled trades."""
    trades = [t for t in _load()["trades"] if t["settled"]]
    if not trades:
        return {"settled": 0, "win_rate": None, "total_pnl": 0.0, "roi": None}

    wins = sum(1 for t in trades if t["pnl"] and t["pnl"] > 0)
    total = sum(t["pnl"] for t in trades if t["pnl"] is not None)
    capital = sum(t["cost"] for t in trades if t["cost"] is not None)
    return {
        "settled": len(trades),
        "open": len(get_open_trades()),
        "wins": wins,
        "win_rate": wins / len(trades),
        "total_pnl": round(total, 2),
        "roi": round(total / capital, 4) if capital else None,
        "balance": round(get_balance(), 2),
    }


def reset_paper_account() -> None:
    """Wipe all paper trades and reset balance."""
    _save({"balance": STARTING_BALANCE, "trades": []})
