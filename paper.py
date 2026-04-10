"""
Paper trading ledger — simulates trades without using real money.
Stored in data/paper_trades.json. Tracks:
  - Entry: ticker, side, quantity, entry_price, entry_prob
  - Exit/settlement: outcome, P&L
"""

from __future__ import annotations

import csv
import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path

from safe_io import AtomicWriteError, atomic_write_json
from utils import FIXED_BET_DOLLARS, FIXED_BET_PCT, KALSHI_FEE_RATE, STRATEGY

_log = logging.getLogger(__name__)

DATA_PATH = Path(__file__).parent / "data" / "paper_trades.json"
DATA_PATH.parent.mkdir(exist_ok=True)

STARTING_BALANCE = 1000.0  # default paper bankroll in dollars
# #121: drawdown halt configurable via env (default 50%)
MAX_DRAWDOWN_FRACTION = float(os.getenv("DRAWDOWN_HALT_PCT", "0.50"))

MAX_DAILY_LOSS_PCT = float(os.getenv("MAX_DAILY_LOSS_PCT", "0.03"))  # default 3%
MAX_POSITION_AGE_DAYS = int(os.getenv("MAX_POSITION_AGE_DAYS", "7"))

# Gradual recovery thresholds (fraction of peak balance).
# Conservative tiers: resume slowly after a loss streak to avoid blowup.
_DRAWDOWN_TIER_1 = 1 - MAX_DRAWDOWN_FRACTION  # 0.50 — fully paused below this
_DRAWDOWN_TIER_2 = 0.60  # 10% sizing (was 25%)
_DRAWDOWN_TIER_3 = 0.75  # 30% sizing (was 50%)
_DRAWDOWN_TIER_4 = 0.90  # 70% sizing (was 75%)

MAX_TOTAL_OPEN_EXPOSURE = (
    0.50  # max fraction of starting balance in open positions total
)
MAX_CITY_DATE_EXPOSURE = 0.15  # max fraction of starting balance on one city/date combo
MAX_DIRECTIONAL_EXPOSURE = (
    0.10  # max fraction of starting balance on one city/date/side
)

# Cities that tend to move together due to shared weather patterns.
_CORRELATED_CITY_GROUPS = [
    {"NYC", "Boston"},
    {"Chicago", "Denver"},
    {"LA", "Phoenix"},
    {"Dallas", "Atlanta"},
]
MAX_CORRELATED_EXPOSURE = 0.20  # max combined fraction across a correlated group

# #51: Pairwise city temperature correlations for portfolio Kelly covariance matrix.
# Values are approximate correlations of daily high-temperature anomalies.
# Symmetric; self-correlation = 1.0 (not listed).
_CITY_PAIR_CORR: dict[frozenset, float] = {
    frozenset({"NYC", "Boston"}): 0.85,
    frozenset({"NYC", "Philadelphia"}): 0.80,
    frozenset({"Chicago", "Denver"}): 0.45,
    frozenset({"Chicago", "Minneapolis"}): 0.60,
    frozenset({"LA", "Phoenix"}): 0.55,
    frozenset({"LA", "San Francisco"}): 0.50,
    frozenset({"Dallas", "Atlanta"}): 0.55,
    frozenset({"Dallas", "Houston"}): 0.70,
    frozenset({"Miami", "Atlanta"}): 0.50,
}
MAX_SINGLE_TICKER_EXPOSURE = float(
    os.getenv("MAX_SINGLE_TICKER_EXPOSURE", "0.10")
)  # #47
MIN_ORDER_COST = 0.05  # #42: minimum order size in dollars


_SCHEMA_VERSION = 2  # increment when adding new required fields


def _load() -> dict:
    if DATA_PATH.exists():
        with open(DATA_PATH) as f:
            data = json.load(f)
        # #100: auto-migrate older schema versions
        if "_version" not in data:
            data["_version"] = 1
        return data
    return {
        "_version": _SCHEMA_VERSION,
        "balance": STARTING_BALANCE,
        "peak_balance": STARTING_BALANCE,
        "trades": [],
    }


def cleanup_temp_files() -> int:
    """
    #101: Remove stray .paper_trades_* temp files left by interrupted atomic writes.
    Call on startup to prevent accumulation.
    Returns number of files removed.
    """
    count = 0
    for f in DATA_PATH.parent.glob(".paper_trades_*.json"):
        try:
            f.unlink()
            count += 1
        except OSError:
            pass
    return count


def _save(data: dict) -> None:
    """Write atomically with retry via safe_io (#8)."""
    try:
        atomic_write_json(data, DATA_PATH, retries=3)
    except AtomicWriteError as e:
        _log.error("CRITICAL: Could not save paper trades: %s", e)
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
    #41: Uses linear interpolation to eliminate discontinuities between tiers:
      <50% of peak  → 0.00  (fully paused)
      50–100%       → linear scale 0.0 → 1.0
    """
    peak = get_peak_balance()
    if peak <= 0:
        return 1.0
    recovery = get_balance() / peak
    if recovery < _DRAWDOWN_TIER_1:
        return 0.0
    # Linear ramp from 0.0 at 50% recovery → 1.0 at 100% recovery
    return min(1.0, (recovery - _DRAWDOWN_TIER_1) / (1.0 - _DRAWDOWN_TIER_1))


def kelly_bet_dollars(kelly_fraction: float) -> float:
    """
    Return the dollar amount to bet.
    #120: Respects STRATEGY env var:
      kelly:         half-Kelly × balance (default)
      fixed_pct:     FIXED_BET_PCT × balance regardless of Kelly
      fixed_dollars: FIXED_BET_DOLLARS flat per trade
    Applies drawdown scaling and streak pause regardless of strategy.
    """
    scale = drawdown_scaling_factor()
    if scale == 0.0:
        return 0.0
    balance = get_balance()

    if STRATEGY == "fixed_pct":
        dollars = round(balance * min(FIXED_BET_PCT, 0.25), 2)
    elif STRATEGY == "fixed_dollars":
        dollars = min(FIXED_BET_DOLLARS, balance)
    else:
        # Default: half-Kelly, hard cap at 25% of balance
        fraction = max(0.0, min(kelly_fraction * scale, 0.25))
        dollars = round(balance * fraction, 2)

    if is_streak_paused():
        dollars = round(dollars * 0.50, 2)
    return dollars


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
    exit_target: float
    | None = None,  # take-profit price (0–1); exit if market reaches this
    thesis: str | None = None,
) -> dict:
    """
    Place a paper trade. Deducts quantity * entry_price from balance.
    exit_target: optional take-profit price — if set, check_exit_targets() will
    settle this trade early when the market price reaches the target.
    thesis: optional free-text rationale for the trade.
    Returns the trade record.
    """
    if is_daily_loss_halted():
        daily_pnl = get_daily_pnl()
        raise ValueError(
            f"Daily loss limit reached — trading halted for today. (${daily_pnl:.2f} lost)"
        )

    data = _load()
    cost = quantity * entry_price

    # #42: enforce minimum order size
    if cost < MIN_ORDER_COST:
        raise ValueError(
            f"Order too small (${cost:.2f}). Minimum order is ${MIN_ORDER_COST:.2f}."
        )

    # #47: enforce single-ticker exposure cap
    if (
        get_ticker_exposure(ticker) + cost / STARTING_BALANCE
        > MAX_SINGLE_TICKER_EXPOSURE
    ):
        raise ValueError(
            f"Single-ticker exposure cap reached for {ticker} "
            f"(max {MAX_SINGLE_TICKER_EXPOSURE:.0%} of starting balance)."
        )

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
        "exit_target": exit_target,
        "thesis": thesis,
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
            # Fee is charged on winnings (profit) only, not the full $1 payout.
            # net_payout_per_contract = 1.0 - winnings * fee_rate
            entry_price = t["entry_price"]
            winnings_per_contract = 1.0 - entry_price
            net_payout_per_contract = 1.0 - winnings_per_contract * KALSHI_FEE_RATE
            payout = qty * net_payout_per_contract if won else 0.0
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


def get_total_exposure() -> float:
    """
    Return the total fraction of STARTING_BALANCE committed across all open trades.
    Used to enforce the global portfolio cap (MAX_TOTAL_OPEN_EXPOSURE).
    """
    committed = sum(t["cost"] for t in get_open_trades())
    return committed / STARTING_BALANCE


def get_ticker_exposure(ticker: str) -> float:
    """Return fraction of STARTING_BALANCE committed to open trades for this ticker (#47)."""
    committed = sum(t["cost"] for t in get_open_trades() if t.get("ticker") == ticker)
    return committed / STARTING_BALANCE


def position_age_kelly_scale(ticker: str) -> float:
    """
    #44: Scale down Kelly if we already hold an aging position in this ticker.
    Returns 1.0 if no existing position; scales toward 0.0 at MAX_POSITION_AGE_DAYS.
    """
    existing = [t for t in get_open_trades() if t.get("ticker") == ticker]
    if not existing:
        return 1.0
    now = datetime.now(UTC)
    max_age = 0
    for t in existing:
        try:
            entered = datetime.fromisoformat(t["entered_at"].replace("Z", "+00:00"))
            age = (now - entered).days
            max_age = max(max_age, age)
        except (ValueError, TypeError):
            pass
    if MAX_POSITION_AGE_DAYS <= 0:
        return 1.0
    return max(0.0, 1.0 - max_age / MAX_POSITION_AGE_DAYS)


def get_correlated_exposure(city: str, target_date_str: str) -> float:
    """
    Return the total fraction of STARTING_BALANCE committed to open trades
    in cities correlated with the given city on the same date.
    Correlated cities share weather patterns (e.g. NYC+Boston, LA+Phoenix).
    """
    group = next(
        (g for g in _CORRELATED_CITY_GROUPS if city in g),
        None,
    )
    if not group:
        return 0.0
    return (
        sum(
            t["cost"]
            for t in get_open_trades()
            if t.get("city") in group and t.get("target_date") == target_date_str
        )
        / STARTING_BALANCE
    )


def check_exit_targets(client=None) -> int:
    """
    Scan open paper trades with exit_target set. If the current market price
    has reached or exceeded the target, settle the trade as a win.
    Requires a Kalshi client to fetch current prices; skips if not provided.
    Returns number of trades exited.
    """
    if client is None:
        return 0
    open_trades = [t for t in get_open_trades() if t.get("exit_target") is not None]
    exited = 0
    for t in open_trades:
        try:
            market = client.get_market(t["ticker"])
            yes_bid = market.get("yes_bid") or 0
            if isinstance(yes_bid, int) and yes_bid > 1:
                yes_bid = yes_bid / 100.0
            current_price = float(yes_bid)
            target = t["exit_target"]
            # Exit YES trade if current YES bid >= exit target
            # Exit NO trade if current YES bid <= (1 - exit_target)
            should_exit = (t["side"] == "yes" and current_price >= target) or (
                t["side"] == "no" and current_price <= 1 - target
            )
            if should_exit:
                settle_paper_trade(t["id"], outcome_yes=(t["side"] == "yes"))
                exited += 1
        except Exception:
            continue
    return exited


def portfolio_kelly_fraction(
    base_fraction: float,
    city: str | None,
    target_date_str: str | None,
    side: str | None = None,
    ticker: str | None = None,
) -> float:
    """
    Scale down base_fraction based on existing open exposure to this city/date.
    Also applies:
    - 50% directional penalty if >MAX_DIRECTIONAL_EXPOSURE on same side
    - Continuous correlated-city penalty: Kelly scales linearly from 1.0→0.3
      as group exposure grows from 0→MAX_CORRELATED_EXPOSURE (instead of a
      hard binary cliff). At the cap, sizing is 30% of base.

    If existing city/date exposure >= MAX_CITY_DATE_EXPOSURE, returns 0.0.
    """
    # Global cap: halt new positions if total open exposure >= 50% of starting balance
    if get_total_exposure() >= MAX_TOTAL_OPEN_EXPOSURE:
        return 0.0

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

    # Continuous correlated-city penalty:
    # As group exposure rises from 0 → MAX_CORRELATED_EXPOSURE, Kelly falls
    # linearly from 1.0 → 0.3. Beyond the cap it stays at 0.3.
    corr_exp = get_correlated_exposure(city, target_date_str)
    if corr_exp > 0 and MAX_CORRELATED_EXPOSURE > 0:
        ratio = min(corr_exp / MAX_CORRELATED_EXPOSURE, 1.0)
        corr_scale = 1.0 - ratio * 0.70  # 1.0 at 0%, 0.3 at 100% of cap
        result *= corr_scale

    # #44: scale down Kelly based on age of existing position in this ticker
    if ticker:
        result *= position_age_kelly_scale(ticker)

    # #51: covariance-based Kelly reduction — shrinks bet when correlated positions open
    if side:
        base_prob = (
            base_fraction  # use base_fraction as proxy when entry_prob unavailable
        )
        result *= covariance_kelly_scale(city, base_prob, side)

    return round(result, 6)


def covariance_kelly_scale(
    new_city: str,
    new_prob: float,
    new_side: str,
) -> float:
    """
    #51: Portfolio Kelly covariance adjustment.

    Computes the marginal increase in portfolio variance from adding a new bet,
    using the pairwise city correlation matrix.  Returns a scale in [0.3, 1.0]:
      1.0 — no correlated open positions (full Kelly)
      0.3 — maximum correlation with existing book (30% of Kelly)

    For a binary outcome with win-probability p, the outcome variance is p*(1-p).
    The portfolio variance contribution of a new bet on city A is:
      sigma_A^2 + 2 * sum_i( corr(A,i) * sigma_A * sigma_i * w_i )
    where w_i is the fraction-of-balance in open position i.

    We normalise this by sigma_A^2 so it's independent of bet size, then map
    the ratio linearly to [1.0, 0.3].
    """
    open_trades = get_open_trades()
    if not open_trades:
        return 1.0

    p_new = new_prob if new_side == "yes" else 1.0 - new_prob
    p_new = max(0.01, min(0.99, p_new))
    sigma_new = (p_new * (1 - p_new)) ** 0.5

    # Compute weighted sum of correlations with open positions
    weighted_corr_sum = 0.0
    total_weight = 0.0
    for t in open_trades:
        t_city = t.get("city") or ""
        if not t_city or t_city == new_city:
            continue
        pair = frozenset({new_city, t_city})
        corr = _CITY_PAIR_CORR.get(pair, 0.0)
        if corr == 0.0:
            continue
        p_i = t.get("entry_prob") or 0.5
        p_i = max(0.01, min(0.99, float(p_i)))
        sigma_i = (p_i * (1 - p_i)) ** 0.5
        w_i = t.get("cost", 0.0) / max(STARTING_BALANCE, 1.0)
        weighted_corr_sum += corr * sigma_i * w_i
        total_weight += w_i

    if weighted_corr_sum <= 0 or sigma_new <= 0:
        return 1.0

    # Marginal variance ratio: how much does this bet inflate portfolio variance?
    marginal_ratio = 1.0 + 2.0 * weighted_corr_sum / sigma_new
    # Map ratio linearly: ratio=1 → scale=1.0, ratio=3 → scale=0.3
    scale = max(0.3, 1.0 - (marginal_ratio - 1.0) * 0.35)
    return round(scale, 4)


def slippage_kelly_scale(market: dict, quantity: int) -> float:
    """
    Return a 0.5–1.0 multiplier to reduce Kelly sizing based on market liquidity.
    Thin markets (low volume/open interest) can't absorb large orders without
    moving the price, making paper trade results overly optimistic.
      volume/OI > 500  → 1.00 (liquid)
      200–500          → 0.85
      50–200           → 0.70
      < 50             → 0.50 (illiquid)
    """
    volume = (market.get("volume") or 0) + (market.get("open_interest") or 0)
    if volume > 500:
        return 1.00
    elif volume > 200:
        return 0.85
    elif volume > 50:
        return 0.70
    else:
        return 0.50


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


def check_model_exits(client=None) -> list[dict]:
    """
    For each open paper trade, re-analyze the market and check whether the
    model has reversed or the edge has evaporated.

    Returns a list of exit recommendations:
      [{"trade": {...}, "reason": "model_flipped"|"edge_gone",
        "current_edge": float, "held_side": str}, ...]
    """
    if client is None:
        return []
    open_trades = get_open_trades()
    if not open_trades:
        return []

    from weather_markets import analyze_trade, enrich_with_forecast

    recommendations = []
    for t in open_trades:
        try:
            market = client.get_market(t["ticker"])
            enriched = enrich_with_forecast(market)
            analysis = analyze_trade(enriched)
            if not analysis:
                continue
            held_side = t["side"]
            net_edge = analysis.get("net_edge", analysis["edge"])
            # Model flipped: we're long YES but model now strongly favors NO, or vice versa
            flipped = (held_side == "yes" and net_edge < -0.05) or (
                held_side == "no" and net_edge > 0.05
            )
            # Edge gone: less than 3% after fees — no longer worth holding
            edge_gone = abs(net_edge) < 0.03
            if flipped:
                recommendations.append(
                    {
                        "trade": t,
                        "reason": "model_flipped",
                        "current_edge": round(net_edge, 4),
                        "held_side": held_side,
                    }
                )
            elif edge_gone:
                recommendations.append(
                    {
                        "trade": t,
                        "reason": "edge_gone",
                        "current_edge": round(net_edge, 4),
                        "held_side": held_side,
                    }
                )
        except Exception:
            continue
    return recommendations


def check_expiring_trades(warn_hours: int = 24) -> list[dict]:
    """
    Return open paper trades whose markets close within warn_hours.
    Each entry: {"trade": {...}, "hours_left": float, "urgent": bool}
    urgent=True if < 4 hours remaining.
    Trades without a close_time field are skipped.
    """
    from datetime import UTC, datetime

    open_trades = get_open_trades()
    expiring = []
    now = datetime.now(UTC)
    for t in open_trades:
        close_time_str = t.get("close_time") or t.get("expires_at")
        if not close_time_str:
            continue
        try:
            close_dt = datetime.fromisoformat(close_time_str.replace("Z", "+00:00"))
            hours_left = (close_dt - now).total_seconds() / 3600
            if 0 < hours_left <= warn_hours:
                expiring.append(
                    {
                        "trade": t,
                        "hours_left": round(hours_left, 1),
                        "urgent": hours_left < 4,
                    }
                )
        except (ValueError, TypeError):
            continue
    expiring.sort(key=lambda x: x["hours_left"])  # type: ignore[arg-type, return-value]
    return expiring


def get_current_streak() -> tuple[str, int]:
    """
    Returns ("win", N) or ("loss", N) or ("none", 0) based on the last N consecutive
    settled trades all going the same direction.
    """
    settled = [
        t for t in _load()["trades"] if t["settled"] and t.get("pnl") is not None
    ]
    if not settled:
        return ("none", 0)
    # Sort by entered_at as a proxy for settled time
    settled.sort(key=lambda t: t.get("entered_at", ""))
    # Walk backwards to find streak direction
    last_pnl = settled[-1]["pnl"]
    if last_pnl is None:
        return ("none", 0)
    direction = "win" if last_pnl > 0 else "loss"
    streak = 1
    for t in reversed(settled[:-1]):
        pnl = t.get("pnl")
        if pnl is None:
            break
        trade_dir = "win" if pnl > 0 else "loss"
        if trade_dir == direction:
            streak += 1
        else:
            break
    return (direction, streak)


def is_streak_paused() -> bool:
    """
    #45: Return True if on a 3+ consecutive loss streak AND total streak losses
    exceed 2% of starting balance. Prevents pausing on trivial $0.01 losses.
    """
    kind, n = get_current_streak()
    if kind != "loss" or n < 3:
        return False
    # Check PnL magnitude of the streak, not just count
    settled = [
        t for t in _load()["trades"] if t.get("settled") and t.get("pnl") is not None
    ]
    settled.sort(key=lambda t: t.get("entered_at", ""))
    streak_pnl = sum(t["pnl"] for t in settled[-n:] if t.get("pnl") is not None)
    return streak_pnl < -(STARTING_BALANCE * 0.02)


def get_daily_pnl(client=None) -> float:
    """
    Sum of P&L from trades settled today (UTC).
    #46: If a live client is provided, also includes unrealized MTM of open
    positions so the daily loss limit accounts for positions that are underwater.
    """
    today_str = datetime.now(UTC).strftime("%Y-%m-%d")
    settled_pnl = sum(
        t.get("pnl", 0.0) or 0.0
        for t in _load()["trades"]
        if t.get("settled") and t.get("entered_at", "")[:10] == today_str
    )
    if client is None:
        return settled_pnl
    # Add unrealized MTM for open positions
    try:
        mtm = get_unrealized_pnl_paper(client)
        return settled_pnl + mtm.get("total_unrealized", 0.0)
    except Exception:
        return settled_pnl


def is_daily_loss_halted(client=None) -> bool:
    """Return True if today's P&L is worse than -MAX_DAILY_LOSS_PCT * STARTING_BALANCE.
    Pass a live client to include unrealized MTM in the check (#46).
    """
    return get_daily_pnl(client) < -(MAX_DAILY_LOSS_PCT * STARTING_BALANCE)


def check_aged_positions() -> list[dict]:
    """
    Return open trades entered more than MAX_POSITION_AGE_DAYS days ago.
    Each entry: {"trade": {...}, "age_days": int}
    """
    now = datetime.now(UTC)
    aged = []
    for t in get_open_trades():
        entered_str = t.get("entered_at", "")
        if not entered_str:
            continue
        try:
            entered = datetime.fromisoformat(entered_str.replace("Z", "+00:00"))
            age_days = (now - entered).days
            if age_days > MAX_POSITION_AGE_DAYS:
                aged.append({"trade": t, "age_days": age_days})
        except (ValueError, TypeError):
            continue
    return aged


def graduation_check(min_trades: int = 30, min_win_rate: float = 0.55) -> dict | None:
    """
    Check if paper trading performance warrants going live.
    Returns a summary dict if criteria met, None otherwise.
    #52: Requires 30+ trades (not 10) and 0.55+ win rate (not 0.60) — 10 trades is
    too few to distinguish skill from luck; 0.55 accounts for ~7% Kalshi fee drag.
    Criteria: >= min_trades settled, win_rate >= min_win_rate, total_pnl > 0.
    Returns: {"settled": N, "win_rate": X, "total_pnl": Y, "roi": Z}
    """
    perf = get_performance()
    settled = perf.get("settled", 0)
    win_rate = perf.get("win_rate")
    total_pnl = perf.get("total_pnl", 0.0)
    roi = perf.get("roi")
    if (
        settled >= min_trades
        and win_rate is not None
        and win_rate >= min_win_rate
        and total_pnl > 0
    ):
        return {
            "settled": settled,
            "win_rate": win_rate,
            "total_pnl": total_pnl,
            "roi": roi,
        }
    return None


def fear_greed_index() -> tuple[int, str]:
    """
    Composite 0-100 score. Higher = more confident/greedy.
    Components:
      - Current drawdown (0-30 pts): 30 at no drawdown, 0 at max drawdown
      - Win streak (0-20 pts): 20 for 3+ win streak, 0 for 3+ loss streak
      - Recent win rate (0-30 pts): last 10 settled trades win rate * 30
      - Available balance vs starting (0-20 pts): balance/starting * 20, capped at 20
    Returns (score, label) where label is one of:
      "Fearful"   (<40)
      "Cautious"  (40-55)
      "Neutral"   (55-65)
      "Confident" (65-80)
      "Greedy"    (>80)
    """
    # Component 1: drawdown (0–30)
    dd = get_max_drawdown_pct()
    dd_pts = max(0.0, 30.0 * (1.0 - dd))

    # Component 2: win streak (0–20)
    kind, n = get_current_streak()
    if kind == "win":
        streak_pts = min(20.0, n / 3 * 20.0)
    elif kind == "loss":
        streak_pts = max(0.0, 20.0 - n / 3 * 20.0)
    else:
        streak_pts = 10.0  # neutral

    # Component 3: recent win rate (0–30) — last 10 settled trades
    data = _load()
    settled = [
        t for t in data["trades"] if t.get("settled") and t.get("pnl") is not None
    ]
    recent = settled[-10:] if len(settled) >= 10 else settled
    if recent:
        win_rate = sum(1 for t in recent if (t.get("pnl") or 0) > 0) / len(recent)
    else:
        win_rate = 0.5
    wr_pts = win_rate * 30.0

    # Component 4: balance vs starting (0–20)
    balance = get_balance()
    bal_pts = min(20.0, (balance / STARTING_BALANCE) * 20.0)

    score = int(round(dd_pts + streak_pts + wr_pts + bal_pts))
    score = max(0, min(100, score))

    if score < 40:
        label = "Fearful"
    elif score < 55:
        label = "Cautious"
    elif score < 65:
        label = "Neutral"
    elif score <= 80:
        label = "Confident"
    else:
        label = "Greedy"

    return (score, label)


def check_correlated_event_exposure() -> list[dict]:
    """
    Detect when you have 2+ open positions tied to the same city within
    a 3-day window (same weather event, correlated outcomes).
    Returns list of {"city": str, "dates": list, "trades": list, "total_cost": float}
    """
    from datetime import date

    open_trades = get_open_trades()
    # Only consider trades with city and target_date
    dated_trades = [t for t in open_trades if t.get("city") and t.get("target_date")]

    # Group by city
    by_city: dict[str, list[dict]] = {}
    for t in dated_trades:
        by_city.setdefault(t["city"], []).append(t)

    results = []
    for city, trades in by_city.items():
        if len(trades) < 2:
            continue
        # Sort by date
        try:
            trades_sorted = sorted(
                trades,
                key=lambda t: date.fromisoformat(t["target_date"]),
            )
        except (ValueError, TypeError):
            continue

        # Find clusters within 3-day windows
        used_indices: set[int] = set()
        for i, anchor in enumerate(trades_sorted):
            if i in used_indices:
                continue
            try:
                anchor_date = date.fromisoformat(anchor["target_date"])
            except (ValueError, TypeError):
                continue
            cluster = [anchor]
            cluster_indices = {i}
            for j, other in enumerate(trades_sorted):
                if j == i or j in used_indices:
                    continue
                try:
                    other_date = date.fromisoformat(other["target_date"])
                except (ValueError, TypeError):
                    continue
                if abs((other_date - anchor_date).days) <= 3:
                    cluster.append(other)
                    cluster_indices.add(j)

            if len(cluster) >= 2:
                used_indices |= cluster_indices
                dates = sorted({t["target_date"] for t in cluster})
                total_cost = sum(t.get("cost", 0.0) for t in cluster)
                results.append(
                    {
                        "city": city,
                        "dates": dates,
                        "trades": cluster,
                        "total_cost": round(total_cost, 2),
                    }
                )

    return results


def export_tax_csv(path: str, tax_year: int | None = None) -> int:
    """
    Export settled trades in Schedule D / capital gains format.
    Columns: Description, Date Acquired, Date Sold, Proceeds, Cost Basis, Gain/Loss
    If tax_year is specified, only include trades settled in that year.
    Returns row count.
    Note: this is for informational purposes only, not tax advice.
    """
    import csv

    all_trades = get_all_trades()
    settled = [t for t in all_trades if t.get("settled")]

    if tax_year is not None:
        filtered = []
        for t in settled:
            # Use entered_at as a proxy for date sold (we don't track settled_at separately)
            date_str = (t.get("entered_at") or "")[:4]
            if date_str == str(tax_year):
                filtered.append(t)
        settled = filtered

    if not settled:
        return 0

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "Description",
                "Date Acquired",
                "Date Sold",
                "Proceeds",
                "Cost Basis",
                "Gain/Loss",
            ]
        )
        for t in settled:
            desc = f"Kalshi {t.get('ticker', '')} {t.get('side', '').upper()}"
            date_acq = (t.get("entered_at") or "")[:10]
            date_sold = date_acq  # same day for paper trades (simplified)
            pnl = t.get("pnl") or 0.0
            cost = t.get("cost") or 0.0
            proceeds = round(cost + pnl, 4)
            writer.writerow([desc, date_acq, date_sold, proceeds, cost, pnl])

    return len(settled)


def get_balance_history() -> list[dict]:
    """
    Return a time-ordered list of balance snapshots derived from the trade ledger.
    Each entry: {"ts": ISO string, "balance": float, "event": str}
    Starts at STARTING_BALANCE, applies each trade entry/exit in order.
    """
    all_trades = _load()["trades"]
    # Sort by entered_at ascending
    sorted_trades = sorted(all_trades, key=lambda t: t.get("entered_at", ""))
    balance = STARTING_BALANCE
    history = [{"ts": "", "balance": balance, "event": "Start"}]
    for t in sorted_trades:
        entered_at = t.get("entered_at", "")
        cost = t.get("cost", 0.0) or 0.0
        ticker = t.get("ticker", "")
        # Entry: deduct cost
        balance -= cost
        history.append(
            {
                "ts": entered_at,
                "balance": round(balance, 4),
                "event": f"Bought {ticker}",
            }
        )
        # Settlement: add payout if settled
        if t.get("settled") and t.get("pnl") is not None:
            pnl = t["pnl"]
            payout = cost + pnl
            balance += payout
            # Sort after entry by appending "z" suffix for stable ordering
            history.append(
                {
                    "ts": entered_at + "z",
                    "balance": round(balance, 4),
                    "event": f"Settled {ticker} {t.get('outcome', '')}",
                }
            )
    return history


def undo_last_trade(max_minutes: int = 5) -> dict | None:
    """
    Reverse the most recently placed (unsettled) paper trade if it was placed
    within max_minutes ago. Refunds the cost to balance.
    Returns the removed trade dict, or None if nothing to undo.
    """
    data = _load()
    unsettled = [t for t in data["trades"] if not t["settled"]]
    if not unsettled:
        return None
    # Sort by entered_at descending to get the most recent
    unsettled.sort(key=lambda t: t.get("entered_at", ""), reverse=True)
    last = unsettled[0]
    entered_str = last.get("entered_at", "")
    if not entered_str:
        return None
    try:
        entered_dt = datetime.fromisoformat(entered_str.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    elapsed_minutes = (datetime.now(UTC) - entered_dt).total_seconds() / 60
    if elapsed_minutes > max_minutes:
        return None
    # Refund cost and remove from trades
    cost = last.get("cost", 0.0) or 0.0
    data["balance"] += cost
    data["trades"] = [t for t in data["trades"] if t["id"] != last["id"]]
    # Recalculate peak_balance from remaining trades
    peak = STARTING_BALANCE
    running = STARTING_BALANCE
    for t in sorted(data["trades"], key=lambda t: t.get("entered_at", "")):
        running -= t.get("cost", 0.0) or 0.0
        if t.get("settled") and t.get("pnl") is not None:
            payout = (t.get("cost", 0.0) or 0.0) + t["pnl"]
            running += payout
            peak = max(peak, running)
    data["peak_balance"] = max(peak, data["balance"])
    _save(data)
    return last


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


# ── Portfolio analytics ───────────────────────────────────────────────────────


def get_rolling_sharpe(window_days: int = 30) -> float | None:
    """
    Annualised Sharpe ratio over the last window_days calendar days.
    Uses daily P&L from settled trades (trades with no activity on a day = 0).
    Returns None if fewer than 5 days of data.
    """
    import math
    import statistics
    from datetime import UTC, datetime, timedelta

    cutoff = (datetime.now(UTC) - timedelta(days=window_days)).strftime("%Y-%m-%d")
    settled = [
        t
        for t in _load()["trades"]
        if t.get("settled") and (t.get("entered_at", "") or "")[:10] >= cutoff
    ]
    if not settled:
        return None

    # Build daily P&L map
    daily: dict[str, float] = {}
    for t in settled:
        day = (t.get("entered_at", "") or "")[:10]
        if day:
            daily[day] = daily.get(day, 0.0) + (t.get("pnl") or 0.0)

    if len(daily) < 5:
        return None

    values = list(daily.values())
    mean = statistics.mean(values)
    stdev = statistics.stdev(values)
    if stdev == 0:
        return None
    return round(mean / stdev * math.sqrt(252), 4)


def get_attribution() -> dict:
    """
    Decompose P&L into model-edge contribution vs luck (residual).
    Expected P&L = probability * winnings - cost (what an EV-maximiser earns on average).
    Luck = actual P&L - expected P&L.
    """
    settled = [
        t for t in _load()["trades"] if t.get("settled") and t.get("pnl") is not None
    ]
    pnl_from_edge = 0.0
    pnl_from_luck = 0.0

    for t in settled:
        ep = t.get("entry_prob") or 0.5
        entry_price = t.get("entry_price", 0.5) or 0.5
        qty = t.get("quantity", 1) or 1
        cost = t.get("cost", 0.0) or 0.0
        winnings_per = 1.0 - entry_price
        # Expected P&L if we could repeat this bet infinitely at our model's probability
        expected = ep * (qty * (1.0 - winnings_per * KALSHI_FEE_RATE)) - cost
        actual = t["pnl"]
        pnl_from_edge += expected
        pnl_from_luck += actual - expected

    total = pnl_from_edge + pnl_from_luck
    return {
        "pnl_from_edge": round(pnl_from_edge, 4),
        "pnl_from_luck": round(pnl_from_luck, 4),
        "total_pnl": round(total, 4),
        "n": len(settled),
    }


def get_factor_exposure() -> dict:
    """
    Directional bias across open positions.
    Returns YES/NO counts, costs, and which cities are on each side.
    """
    open_trades = get_open_trades()
    yes_count = no_count = 0
    yes_cost = no_cost = 0.0
    cities_yes: list[str] = []
    cities_no: list[str] = []

    for t in open_trades:
        side = t.get("side", "yes")
        cost = t.get("cost", 0.0) or 0.0
        city = t.get("city") or ""
        if side == "yes":
            yes_count += 1
            yes_cost += cost
            if city and city not in cities_yes:
                cities_yes.append(city)
        else:
            no_count += 1
            no_cost += cost
            if city and city not in cities_no:
                cities_no.append(city)

    total_cost = yes_cost + no_cost
    if total_cost > 0:
        yes_frac = yes_cost / total_cost
        if yes_frac > 0.6:
            net_bias = "YES-heavy"
        elif yes_frac < 0.4:
            net_bias = "NO-heavy"
        else:
            net_bias = "Balanced"
    else:
        net_bias = "Balanced"

    return {
        "yes_count": yes_count,
        "no_count": no_count,
        "yes_cost": round(yes_cost, 4),
        "no_cost": round(no_cost, 4),
        "net_bias": net_bias,
        "cities_long_yes": sorted(cities_yes),
        "cities_long_no": sorted(cities_no),
    }


def get_expiry_date_clustering() -> list[dict]:
    """
    Identify dates with 2+ open positions settling — concentration risk.
    Returns [{date, count, total_cost, tickers}] sorted ascending.
    """
    open_trades = get_open_trades()
    by_date: dict[str, list] = {}
    for t in open_trades:
        d = t.get("target_date") or ""
        if d:
            by_date.setdefault(d, []).append(t)

    result = []
    for date_str, trades in sorted(by_date.items()):
        if len(trades) < 2:
            continue
        result.append(
            {
                "date": date_str,
                "count": len(trades),
                "total_cost": round(sum(t.get("cost", 0.0) or 0.0 for t in trades), 4),
                "tickers": [t.get("ticker", "") for t in trades],
            }
        )
    return result


def get_unrealized_pnl_paper(client) -> dict:
    """
    Mark-to-market unrealized P&L for open paper positions.
    Fetches current YES bid from Kalshi to estimate position value.
    Returns {total_unrealized, by_trade: [{id, ticker, mark_pnl, current_price}], n}.
    """
    open_trades = get_open_trades()
    if not open_trades or client is None:
        return {"total_unrealized": 0.0, "by_trade": [], "n": 0}

    by_trade = []
    total = 0.0

    for t in open_trades:
        try:
            market = client.get_market(t["ticker"])
            yes_bid = market.get("yes_bid") or 0
            if isinstance(yes_bid, int | float) and yes_bid > 1:
                yes_bid = yes_bid / 100.0
            current = float(yes_bid) if yes_bid else None
            if current is None or current <= 0:
                continue

            entry = t.get("entry_price", 0.5) or 0.5
            qty = t.get("quantity", 1) or 1
            side = t.get("side", "yes")

            if side == "yes":
                mark_pnl = (current - entry) * qty
            else:
                mark_pnl = ((1.0 - current) - entry) * qty

            total += mark_pnl
            by_trade.append(
                {
                    "id": t.get("id"),
                    "ticker": t.get("ticker", ""),
                    "mark_pnl": round(mark_pnl, 4),
                    "current_price": round(current, 4),
                }
            )
        except Exception:
            continue

    return {
        "total_unrealized": round(total, 4),
        "by_trade": by_trade,
        "n": len(by_trade),
    }


def check_position_limits(
    ticker: str,
    qty: int,
    price: float = 0.5,
    max_cost_per_market: float = 250.0,
) -> dict:
    """
    Check whether adding qty contracts at price would breach position limits.
    Checks per-market cost cap and global portfolio cap.
    Returns {ok, reason, existing_cost, limit}.
    """
    existing_cost = sum(
        t.get("cost", 0.0) or 0.0
        for t in get_open_trades()
        if t.get("ticker") == ticker
    )
    new_cost = qty * price
    projected = existing_cost + new_cost

    if projected > max_cost_per_market:
        return {
            "ok": False,
            "reason": f"Would exceed per-market cap (${max_cost_per_market:.0f}): ${projected:.2f}",
            "existing_cost": round(existing_cost, 4),
            "limit": max_cost_per_market,
        }

    if get_total_exposure() + new_cost / STARTING_BALANCE >= MAX_TOTAL_OPEN_EXPOSURE:
        return {
            "ok": False,
            "reason": "Would exceed global portfolio exposure cap (50%)",
            "existing_cost": round(existing_cost, 4),
            "limit": max_cost_per_market,
        }

    return {
        "ok": True,
        "reason": None,
        "existing_cost": round(existing_cost, 4),
        "limit": max_cost_per_market,
    }
