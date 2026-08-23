"""Shared position read-model for paper and live trading.

Both paper.py (JSON-ledger positions) and order_executor.py (execution_log
SQLite positions) reduce an open position to the same handful of fields for
stop-loss/breakeven/peak-profit protection. Before this module existed, that
reduction happened twice, independently -- order_executor._get_live_open_positions
built a paper-shaped dict by hand, and _update_live_peak_profits replicated
paper.update_peak_profits' math because that function ignored its own
open_trades parameter and reloaded paper's JSON store internally, so it
couldn't be reused directly. See backlog.txt's "PAPER AND LIVE POSITIONS ARE
TWO LEDGERS WITH ADAPTER GLUE" entry for the full history.

This module is now the single place the read-side shape and the
stop-loss/breakeven/peak math live, so a fix to one (e.g. the
liquidation-price bid/ask convention) can't drift between paper and live the
way it already had before. Storage stays separate on purpose -- paper.py's
JSON ledger and execution_log's SQLite schema each carry many fields these
functions never touch (thesis, model_forecast_means, response, ...); each
side's own PositionStore (paper.PaperPositionStore, order_executor.LivePositionStore)
adapts its native storage into/out of the shared Position shape.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

_log = logging.getLogger(__name__)


@dataclass
class Position:
    """The subset of an open position's fields NOT the full stored record on
    either side -- paper's trade dict and execution_log's order row both
    carry many more fields (thesis, model_forecast_means, response, error,
    ...) that get_open()/save_peak()/exit() below never touch; see
    PaperPositionStore/LivePositionStore for the full-record adapters.

    check_stop_losses/check_breakeven_stops/update_peak_profits (below) only
    read id/ticker/side/quantity/entry_price/cost/close_time/peak_profit_pct.
    entry_prob and entered_at exist for check_model_exits/
    _check_live_model_exits/_check_early_exits (paper.py/order_executor.py),
    which now also source positions via this dataclass (batch-18, via
    _trade_to_position/_live_dict_to_position, built per-item inside each
    function's own try/except rather than a batched list comprehension, so
    one malformed record doesn't drop every position that cycle) -- their
    external return contracts are unchanged, so check_model_exits still
    returns the full raw trade dict (the same loop variable each Position
    was built from, not a separate id lookup) rather than a
    Position, since its callers read fields (thesis, full market dict) this
    dataclass deliberately doesn't carry.
    """

    id: int
    ticker: str
    side: str  # "yes" / "no"
    quantity: int
    entry_price: float
    cost: float
    entry_prob: float | None
    close_time: str | None
    entered_at: str | None
    peak_profit_pct: float | None


class PositionStore(Protocol):
    """The genuinely shared surface between paper.PaperPositionStore and
    order_executor.LivePositionStore -- structural typing (Protocol, not an
    ABC; this repo has no other ABC/Protocol precedent) so mypy flags a
    future divergence between the two implementations' get_open/save_peak
    signatures without either needing to inherit from this.

    Deliberately NOT covering exit(): the two implementations' exit()
    genuinely differ in both return type and reason default, mirroring the
    production functions they each wrap -- paper's exit() returns the dict
    close_paper_early() already returns (check_paper_position_exits' own
    external contract needs its "pnl" key), while live's exit() returns the
    bool _exit_live_position() already returns (True only on a full fill).
    Neither store's exit() is ever called polymorphically through this
    Protocol -- each orchestrator (check_paper_position_exits,
    _check_live_position_exits) only ever calls its own concrete store's
    exit() directly -- so forcing a common signature here would mean either
    changing those two already-relied-on functions' own signatures, or
    lying about what exit() returns. get_open()/save_peak() have no such
    tension: both really are used identically (save_peak is passed as a
    bound callback into update_peak_profits() below).
    """

    def get_open(self) -> list[Position]: ...
    def save_peak(self, position: Position, peak_profit_pct: float) -> None: ...


def liquidation_price(
    prices: dict[str, dict[str, float]], ticker: str, side: str
) -> float | None:
    """Return what closing this position right now would actually realize.

    A YES holder can only sell at yes_bid (what a buyer will pay); a NO
    holder can only sell at 1 - yes_ask (= no_bid). Using yes_ask for YES or
    1 - yes_bid for NO instead prices the position at what a *buyer* would
    pay to open more, not what a *holder* can realize by closing --
    overvaluing the position by the bid-ask spread (understating loss, so
    stops fire late; inflating take-profit/exit proceeds).
    """
    quote = prices.get(ticker)
    if not quote:
        return None
    # parse_market_price() coalesces a missing side to 0.0 (never None) -- a
    # one-sided/thin book with no resting bids (or no resting asks) is
    # common overnight and legitimately produces bid=0.0 or ask=0.0 while
    # the *other* side still has a real quote, so a "has a quote at all"
    # check on the pair can be True while one individual side is still 0.
    # Treating a 0.0 side as a real price fires phantom $0 stop-losses (YES,
    # bid=0) and books phantom $1.00 wins (NO, ask=0) -- both silently
    # corrupt the real ledger. A price <= 0 is never a real tradeable quote,
    # so treat it the same as "no quote" (None) here.
    if side == "yes":
        bid = quote.get("bid")
        return bid if bid is not None and bid > 0 else None
    ask = quote.get("ask")
    return (1.0 - ask) if ask is not None and ask > 0 else None


def _passes_exit_gates(
    *,
    ticker: str,
    log_tag: str,
    entered_at: str | None = None,
    close_time: str | None = None,
    min_hold_hours: float | None = None,
    settlement_gate_hours: float | None = None,
) -> bool:
    """Shared timing gates for early-exit checks (stop-loss/breakeven/model-exit),
    used by this module's own stop-loss/breakeven checks and, independently,
    by paper.check_model_exits/order_executor._check_live_model_exits/
    order_executor._check_early_exits (which apply their own gate
    combinations -- see each call site for which gates it uses and why).

    Pass min_hold_hours to enforce the minimum-hold gate, settlement_gate_hours
    to enforce the pre-settlement gate; leave either None to skip that gate
    entirely -- no call site should start applying a gate it didn't before.

    The two gates fail differently by design: a missing/unparseable
    entered_at fails OPEN (hold gate treated as passed -- we cannot assess
    hold time, so don't block on it), while a missing/unparseable close_time
    fails CLOSED (settlement gate treated as failed, with a warning --
    silently skipping it risks closing at settlement-convergence prices).
    """
    if min_hold_hours is not None and entered_at:
        try:
            entered_dt = datetime.fromisoformat(entered_at.replace("Z", "+00:00"))
            if entered_dt.tzinfo is None:
                entered_dt = entered_dt.replace(tzinfo=UTC)
            hours_held = (datetime.now(UTC) - entered_dt).total_seconds() / 3600
            if hours_held < min_hold_hours:
                return False
        except (ValueError, TypeError):
            pass  # fail open — same as the original inline `except: pass`

    if settlement_gate_hours is not None:
        if not close_time:
            _log.warning(
                "%s skipping exit for %s — close_time missing, cannot apply %gh gate",
                log_tag,
                ticker,
                settlement_gate_hours,
            )
            return False
        try:
            close_dt = datetime.fromisoformat(close_time.replace("Z", "+00:00"))
            hours_to_settlement = (close_dt - datetime.now(UTC)).total_seconds() / 3600
            if hours_to_settlement < settlement_gate_hours:
                return False
        except (ValueError, TypeError):
            _log.warning(
                "%s skipping exit for %s — close_time unparseable: %s",
                log_tag,
                ticker,
                close_time,
            )
            return False

    return True


def check_stop_losses(
    positions: list[Position], current_prices: dict[str, dict[str, float]]
) -> list[Position]:
    """Return positions whose unrealized loss has breached the stop-loss threshold.

    Stop fires when: unrealized_loss > cost / STOP_LOSS_MULT
    i.e. for default STOP_LOSS_MULT=2, exit when the position has lost >50% of cost.

    current_prices: {ticker: {"bid": yes_bid, "ask": yes_ask}} (0-1 floats)
    """
    from utils import EXIT_SETTLEMENT_GATE_HOURS, STOP_LOSS_MULT

    if STOP_LOSS_MULT <= 0:
        return []

    exits: list[Position] = []
    for pos in positions:
        if not pos.ticker or pos.quantity <= 0 or pos.cost <= 0:
            continue

        # In the final EXIT_SETTLEMENT_GATE_HOURS before settlement, binary
        # markets converge to the actual temperature outcome. Intraday price
        # swings in this window are noise — let the market settle naturally
        # rather than locking in a loss.
        if not _passes_exit_gates(
            ticker=pos.ticker,
            log_tag="[StopLoss]",
            close_time=pos.close_time,
            settlement_gate_hours=EXIT_SETTLEMENT_GATE_HOURS,
        ):
            continue

        current_side_price = liquidation_price(current_prices, pos.ticker, pos.side)
        if current_side_price is None:
            continue

        unrealized_pnl = (current_side_price - pos.entry_price) * pos.quantity
        stop_threshold = -(pos.cost / STOP_LOSS_MULT)

        if unrealized_pnl < stop_threshold:
            exits.append(pos)

    return exits


def check_breakeven_stops(
    positions: list[Position], current_prices: dict[str, dict[str, float]]
) -> list[Position]:
    """Return positions whose break-even stop has triggered.

    Fires when: peak_profit_pct >= BREAKEVEN_TRIGGER_PCT AND current unrealized
    pnl <= 0 (price has fallen back to entry or below). Requires
    update_peak_profits() to have been called first so peak_profit_pct is
    current on every position passed in.

    current_prices: {ticker: {"bid": yes_bid, "ask": yes_ask}} (0-1 floats)
    """
    from utils import BREAKEVEN_TRIGGER_PCT, EXIT_SETTLEMENT_GATE_HOURS

    exits: list[Position] = []
    for pos in positions:
        peak = pos.peak_profit_pct
        if peak is None or peak < BREAKEVEN_TRIGGER_PCT:
            continue

        # Same settlement-convergence gate as check_stop_losses.
        if not _passes_exit_gates(
            ticker=pos.ticker,
            log_tag="[BreakevenStop]",
            close_time=pos.close_time,
            settlement_gate_hours=EXIT_SETTLEMENT_GATE_HOURS,
        ):
            continue

        current_side_price = liquidation_price(current_prices, pos.ticker, pos.side)
        if current_side_price is None:
            continue
        unrealized_pnl = (current_side_price - pos.entry_price) * pos.quantity
        if unrealized_pnl <= 0:
            exits.append(pos)
    return exits


def update_peak_profits(
    positions: list[Position],
    current_prices: dict[str, dict[str, float]],
    save_peak: Callable[[Position, float], None],
) -> bool:
    """Update peak_profit_pct on open positions if current unrealized profit
    is a new high, persisting each update via the injected save_peak callback
    (typically a bound PositionStore.save_peak, so paper positions persist to
    the JSON ledger and live positions persist to execution_log).

    Unlike the pre-refactor paper.update_peak_profits() this replaces, this
    function operates ONLY on the positions list passed in -- it never
    independently reloads a store, so `positions` must already be the
    caller's fresh open-position list (same contract check_stop_losses/
    check_breakeven_stops already had). One save_peak call is made per
    updated position (not batched into one write for the whole list) --
    matches the write pattern order_executor's live path already used;
    paper's old batched-single-save behavior is the one that changes here.

    Mutates each updated Position's peak_profit_pct in place (so a
    subsequent check_breakeven_stops call in the same cycle sees the fresh
    peak) and returns True if any position's peak was updated.
    """
    changed = False
    for pos in positions:
        if pos.cost <= 0 or pos.quantity <= 0:
            continue
        current_side_price = liquidation_price(current_prices, pos.ticker, pos.side)
        if current_side_price is None:
            continue
        unrealized_profit_pct = (
            (current_side_price - pos.entry_price) * pos.quantity / pos.cost
        )
        stored_peak = pos.peak_profit_pct
        if stored_peak is None or unrealized_profit_pct > stored_peak:
            rounded = round(unrealized_profit_pct, 4)
            save_peak(pos, rounded)
            pos.peak_profit_pct = rounded
            changed = True
    return changed
