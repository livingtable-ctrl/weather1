"""
Pass 11 (State) reproductions -- run with pytest against isolated temp DBs only.
Does NOT touch the real execution_log.db (main-clone data/ dir) -- redirects
execution_log.DB_PATH to a tmp_path file before any call, matching
tests/conftest.py's isolate_execution_log fixture pattern.

Run:
    pytest audit/reproductions/pass11_state_repro.py -v
"""
from __future__ import annotations

import importlib


def test_count_open_live_orders_drops_filled_positions(tmp_path, monkeypatch):
    """Reproduces: _count_open_live_orders() (the real max_open_positions gate
    for the live order-placement path, order_executor.py:172-175) only counts
    rows with status == 'pending'. Once a GTC live buy fills (status
    transitions to 'filled' via _poll_pending_orders), it is a genuine open,
    unsettled live POSITION (get_filled_unsettled_live_orders() would report
    it), yet _count_open_live_orders() no longer counts it at all.
    """
    import execution_log

    importlib.reload(execution_log)
    execution_log.DB_PATH = tmp_path / "execution_log_test.db"
    execution_log.DB_PATH.parent.mkdir(exist_ok=True)
    execution_log._initialized = False

    import order_executor

    # Place 3 live buy orders, exactly matching main.py's placement shape
    # (status='pending' at insert, then transitioned to 'pending' after the
    # exchange ack, then 'filled' after _poll_pending_orders observes a fill).
    row_ids = []
    for i in range(3):
        rid = execution_log.log_order(
            ticker=f"KXHIGHNY-26AUG20-T8{i}",
            side="yes",
            quantity=10,
            price=0.5,
            order_type="limit",
            status="pending",
            live=True,
        )
        row_ids.append(rid)

    # All 3 are pending -> gate correctly sees 3 open "positions".
    before = order_executor._count_open_live_orders()

    # Simulate _poll_pending_orders observing fills for all 3 (as would
    # happen automatically within a few cron/watch cycles for GTC orders
    # resting at a competitive price).
    for rid in row_ids:
        execution_log.log_order_result(
            rid, status="filled", fill_quantity=10, filled_at="2026-08-17T00:00:00+00:00"
        )

    after = order_executor._count_open_live_orders()

    # These 3 positions are now genuinely OPEN (unsettled, real capital at
    # risk) per get_filled_unsettled_live_orders() -- the function every
    # other part of this codebase treats as "the real open live positions".
    real_open_positions = len(execution_log.get_filled_unsettled_live_orders())

    print(f"pending-based gate before fills: {before}")
    print(f"pending-based gate after fills:  {after}")
    print(f"actual open live positions:      {real_open_positions}")

    assert before == 3, "sanity: 3 pending orders should count as 3"
    assert real_open_positions == 3, (
        "sanity: all 3 are genuinely open, unsettled live positions"
    )
    # This is the bug: the gate main.py/order_executor.py actually uses to
    # enforce live_config.json's max_open_positions hard-stop reports 0 open
    # positions immediately after they fill, even though 3 real positions
    # with real capital are open and unsettled.
    assert after == 0, (
        "BUG CONFIRMED: _count_open_live_orders() drops filled-but-unsettled "
        "live positions to 0, so max_open_positions never actually bounds "
        "real concurrent live exposure once orders start filling"
    )


def test_auto_place_trades_open_trades_list_is_paper_only(monkeypatch):
    """Reproduces: order_executor._auto_place_trades' MAX_CONCURRENT_POSITIONS
    cap and its VaR gate (portfolio_var) are seeded from paper.get_open_trades()
    (line ~2364: `_open_trades_list = get_open_trades()` where get_open_trades
    is `from paper import get_open_trades`) regardless of live=True/False --
    confirms these never see real execution_log live positions from prior
    cycles."""
    import inspect

    import order_executor

    src = inspect.getsource(order_executor._auto_place_trades)
    assert "_open_trades_list = get_open_trades()" in src
    # get_open_trades is imported from paper (paper.py's JSON ledger), not
    # execution_log -- confirm the import statement in the same function.
    assert "from paper import (" in src
    assert "get_open_trades," in src
    # No execution_log-sourced position list is ever merged in.
    assert "get_filled_unsettled_live_orders" not in src
    assert "_get_live_open_positions" not in src
    print(
        "CONFIRMED: _auto_place_trades' MAX_CONCURRENT_POSITIONS/VaR/"
        "per-date-concentration/corr_kelly_scale gates all read only "
        "paper.get_open_trades() -- blind to real live positions in "
        "execution_log across cron/watch cycles, live=True or not."
    )


def test_cmd_order_partial_manual_sell_row_never_settled(tmp_path):
    """Reproduces: main.py's cmd_order manual-sell path (commit e5331a8d,
    2026-08-17) calls execution_log.record_live_exit_fill() for a matched
    live sell, but -- unlike order_executor._exit_live_position's own
    partial-fill branch (order_executor.py ~1279-1332), which follows up
    with a SECOND call, record_live_early_exit(log_id, ...), to settle the
    EXIT ORDER's own row -- cmd_order never makes that second call. For a
    PARTIAL fill, the manual sell's own execution_log row (closes_position_id
    set, live=1, status='filled') is left with settled_at/pnl/exit_price
    permanently NULL, so it never appears in export_live_tax_csv or
    get_live_pnl_summary's SUM(pnl) totals, even though add_live_loss()
    correctly updated the daily aggregate.
    """
    import execution_log
    import importlib

    importlib.reload(execution_log)
    execution_log.DB_PATH = tmp_path / "execution_log_test2.db"
    execution_log._initialized = False

    # 1. An open live position (as if placed by a prior automated buy).
    position_id = execution_log.log_order(
        ticker="KXHIGHNY-26AUG20-T80",
        side="yes",
        quantity=10,
        price=0.40,
        status="filled",
        live=True,
    )
    execution_log.log_order_result(position_id, status="filled", fill_quantity=10)

    # 2. cmd_order's manual sell of 4 (< 10) contracts -- mirrors main.py's
    # own log_order() call at line ~4653 (closes_position_id set upfront).
    sell_row_id = execution_log.log_order(
        ticker="KXHIGHNY-26AUG20-T80",
        side="yes",
        quantity=4,
        price=0.55,
        status="pending",
        live=True,
        closes_position_id=position_id,
    )
    execution_log.log_order_result(sell_row_id, status="filled", fill_quantity=4)

    # 3. cmd_order's ONLY bookkeeping call for a matched sell (main.py
    # ~4784) -- this is everything cmd_order does today.
    position = {"id": position_id, "quantity": 10, "entry_price": 0.40}
    pnl, fully_closed = execution_log.record_live_exit_fill(position, 4, 0.55)
    assert fully_closed is False
    assert pnl > 0

    # The daily aggregate DID get this fill's P&L (used by the daily-loss gate).
    assert execution_log.get_today_live_loss() != float("inf")

    # But the sell order's OWN row (sell_row_id) -- what export_live_tax_csv
    # and get_live_pnl_summary actually read per-row -- was never settled.
    sell_row = execution_log.get_order_by_id(sell_row_id)
    print(f"sell order row after cmd_order's bookkeeping: {sell_row}")
    assert sell_row["settled_at"] is None, (
        "BUG CONFIRMED: the manual sell's own execution_log row is never "
        "settled for a partial fill -- export_live_tax_csv and "
        "get_live_pnl_summary will never see this lot's P&L"
    )
    assert sell_row["pnl"] is None

    summary = execution_log.get_live_pnl_summary()
    print(f"get_live_pnl_summary: {summary}")
    assert summary["total_pnl"] == 0.0, (
        "the partial manual sell's real, non-zero pnl is invisible to the "
        "dashboard's live P&L summary despite being counted in the daily "
        "aggregate loss/gain total"
    )
