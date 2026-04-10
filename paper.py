"""
Paper trading ledger — simulates trades without using real money.
Stored in data/paper_trades.json. Tracks:
  - Entry: ticker, side, quantity, entry_price, entry_prob
  - Exit/settlement: outcome, P&L
"""

from __future__ import annotations

import csv
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from utils import KALSHI_FEE_RATE

DATA_PATH = Path(__file__).parent / "data" / "paper_trades.json"
DATA_PATH.parent.mkdir(exist_ok=True)

STARTING_BALANCE = 1000.0  # default paper bankroll in dollars
MAX_DRAWDOWN_FRACTION = 0.50  # halt auto-sizing if balance < 50% of peak

# Gradual recovery thresholds (fraction of peak balance)
_DRAWDOWN_TIER_1 = 1 - MAX_DRAWDOWN_FRACTION  # 0.50 — fully paused below this
_DRAWDOWN_TIER_2 = 0.60  # 25% sizing
_DRAWDOWN_TIER_3 = 0.75  # 50% sizing
_DRAWDOWN_TIER_4 = 0.90  # 75% sizing

MAX_CITY_DATE_EXPOSURE = 0.15  # max fraction of starting balance on one city/date combo
MAX_DIRECTIONAL_EXPOSURE = (
    0.10  # max fraction of starting balance on one city/date/side
)


def _load() -> dict:
    if DATA_PATH.exists():
        with open(DATA_PATH) as f:
            return json.load(f)
    return {"balance": STARTING_BALANCE, "peak_balance": STARTING_BALANCE, "trades": []}


def _save(data: dict) -> None:
    """Write atomically: write to a temp file then rename, so a crash never corrupts the ledger."""
    dir_ = DATA_PATH.parent
    fd, tmp = tempfile.mkstemp(dir=dir_, prefix=".paper_trades_", suffix=".json")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, DATA_PATH)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def get_balance() -> float:
    return _load()["balance"]


def get_peak_balance() -> float:
    """Return the highest balance ever reached (high-water mark)."""
    return _load().get("peak_balance", STARTING_BALANCE)


def get_max_drawdown_pct() -> float:
    """Current drawdown from peak as a fraction (0.0 = no drawdown, 1.0 = total loss)."""
    peak = get_peak_balance()
    if peak <= 0:
        return 0.0
    return max(0.0, (peak - get_balance()) / peak)


def is_paused_drawdown() -> bool:
    """
    Return True if balance has fallen more than MAX_DRAWDOWN_FRACTION from the
    peak balance (high-water mark). Auto-sizing is halted; manual qty still works.
    """
    return get_balance() < get_peak_balance() * (1 - MAX_DRAWDOWN_FRACTION)


def drawdown_scaling_factor() -> float:
    """
    Return a 0.0–1.0 multiplier for Kelly sizing based on recovery from peak.
    Gradual steps prevent over-betting during a drawdown while still allowing
    some activity as the balance recovers:
      <50% of peak  → 0.00  (fully paused)
      50–60%        → 0.25
      60–75%        → 0.50
      75–90%        → 0.75
      ≥90%          → 1.00  (normal)
    """
    peak = get_peak_balance()
    if peak <= 0:
        return 1.0
    recovery = get_balance() / peak
    if recovery < _DRAWDOWN_TIER_1:
        return 0.0
    elif recovery < _DRAWDOWN_TIER_2:
        return 0.25
    elif recovery < _DRAWDOWN_TIER_3:
        return 0.50
    elif recovery < _DRAWDOWN_TIER_4:
        return 0.75
    else:
        return 1.0


def kelly_bet_dollars(kelly_fraction: float) -> float:
    """
    Return the dollar amount to bet based on Kelly fraction × current balance.
    Scales down gradually as drawdown deepens rather than cutting off entirely
    at the 50% threshold. Fully pauses below 50% of peak.
    Hard cap at 25% of balance as a safety limit.
    """
    scale = drawdown_scaling_factor()
    if scale == 0.0:
        return 0.0
    balance = get_balance()
    fraction = max(0.0, min(kelly_fraction * scale, 0.25))
    return round(balance * fraction, 2)


def kelly_quantity(
    kelly_fraction: float, price: float, min_dollars: float = 1.0
) -> int:
    """
    Convert a Kelly dollar amount to a quantity (contracts) at a given price.
    Returns 0 if the Kelly allocation would be too small to buy even one contract
    without over-betting (requires at least min_dollars allocated).
    """
    if price <= 0:
        return 0
    dollars = kelly_bet_dollars(kelly_fraction)
    if dollars < min_dollars:
        return 0
    return int(dollars / price)


def place_paper_order(
    ticker: str,
    side: str,  # "yes" or "no"
    quantity: int,
    entry_price: float,
    entry_prob: float | None = None,
    net_edge: float | None = None,
    city: str | None = None,
    target_date: str | None = None,  # ISO format "2026-04-09"
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
        "city": city,
        "target_date": target_date,
        "entered_at": datetime.now(UTC).isoformat(),
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
            payout = qty * 1.0 * (1 - KALSHI_FEE_RATE) if won else 0.0
            pnl = payout - cost

            t["settled"] = True
            t["outcome"] = "yes" if outcome_yes else "no"
            t["pnl"] = round(pnl, 4)
            data["balance"] += payout
            # Update high-water mark after any balance change
            data["peak_balance"] = max(
                data.get("peak_balance", STARTING_BALANCE), data["balance"]
            )
            _save(data)
            return t
    raise ValueError(f"Trade {trade_id} not found or already settled.")


def get_open_trades() -> list[dict]:
    return [t for t in _load()["trades"] if not t["settled"]]


def get_city_date_exposure(city: str, target_date_str: str) -> float:
    """
    Return the fraction of STARTING_BALANCE committed to open trades for
    this city + target date. Uses STARTING_BALANCE as denominator so the
    check stays stable as balance fluctuates.
    """
    committed = sum(
        t["cost"]
        for t in get_open_trades()
        if t.get("city") == city and t.get("target_date") == target_date_str
    )
    return committed / STARTING_BALANCE


def get_directional_exposure(city: str, target_date_str: str, side: str) -> float:
    """
    Return the fraction of STARTING_BALANCE in open trades for this
    city + date + direction (YES or NO). Used to penalise concentrated positions.
    """
    committed = sum(
        t["cost"]
        for t in get_open_trades()
        if t.get("city") == city
        and t.get("target_date") == target_date_str
        and t.get("side") == side
    )
    return committed / STARTING_BALANCE


def portfolio_kelly_fraction(
    base_fraction: float,
    city: str | None,
    target_date_str: str | None,
    side: str | None = None,
) -> float:
    """
    Scale down base_fraction based on existing open exposure to this city/date.
    Also applies a 50% directional penalty if >MAX_DIRECTIONAL_EXPOSURE is already
    on the same side (concentrated correlated bets).

    If existing city/date exposure >= MAX_CITY_DATE_EXPOSURE, returns 0.0.
    """
    if not city or not target_date_str:
        return base_fraction

    existing = get_city_date_exposure(city, target_date_str)
    if existing >= MAX_CITY_DATE_EXPOSURE:
        return 0.0

    room = MAX_CITY_DATE_EXPOSURE - existing
    scale = room / MAX_CITY_DATE_EXPOSURE
    result = base_fraction * scale

    # Directional concentration penalty
    if (
        side
        and get_directional_exposure(city, target_date_str, side)
        > MAX_DIRECTIONAL_EXPOSURE
    ):
        result *= 0.50

    return round(result, 6)


def get_all_trades() -> list[dict]:
    return _load()["trades"]


def get_performance() -> dict:
    """Summary stats across all settled trades."""
    trades = [t for t in _load()["trades"] if t["settled"]]
    if not trades:
        return {
            "settled": 0,
            "win_rate": None,
            "total_pnl": 0.0,
            "roi": None,
            "peak_balance": get_peak_balance(),
            "max_drawdown_pct": get_max_drawdown_pct(),
        }

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
        "peak_balance": round(get_peak_balance(), 2),
        "max_drawdown_pct": round(get_max_drawdown_pct(), 4),
    }


def export_trades_csv(path: str) -> int:
    """Export all paper trades to CSV. Returns number of rows written."""
    trades = get_all_trades()
    if not trades:
        return 0
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(trades[0].keys()))
        writer.writeheader()
        writer.writerows(trades)
    return len(trades)


def reset_paper_account() -> None:
    """Wipe all paper trades and reset balance."""
    _save({"balance": STARTING_BALANCE, "peak_balance": STARTING_BALANCE, "trades": []})


def auto_settle_paper_trades(client=None) -> int:
    """
    Settle any open paper trades whose tickers have recorded outcomes.
    First checks the tracker DB, then falls back to the Kalshi API directly
    for trades that were never logged to the tracker (e.g. manual paper buys).
    Returns the number of trades settled.
    """
    from tracker import get_outcome_for_ticker

    open_trades = get_open_trades()
    settled = 0
    for t in open_trades:
        outcome = get_outcome_for_ticker(t["ticker"])

        # Fallback: query Kalshi API directly if not in tracker
        if outcome is None and client is not None:
            try:
                market = client.get_market(t["ticker"])
                if market.get("status") == "finalized":
                    outcome = market.get("result") == "yes"
            except Exception:
                pass

        if outcome is not None:
            try:
                settle_paper_trade(t["id"], outcome)
                settled += 1
            except Exception:
                pass
    return settled
