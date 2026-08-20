"""Repro: does an exit order's own row (closes_position_id set) get
misread as a "trade already happened" signal by the same-day/duplicate
dedup guards, blocking legitimate re-entry after a stop-loss exit closes
a position?
"""
import os
import pathlib
import sys
import tempfile

tmpdir = tempfile.mkdtemp()
os.environ.setdefault("KALSHI_ENV", "demo")

sys.path.insert(0, r"C:\Users\thesa\claude kalshi\.claude\worktrees\reverent-lumiere-f79c1f")

import execution_log as el  # noqa: E402

# Isolate DB
el.DB_PATH = pathlib.Path(tmpdir) / "execution_log_test.db"
el._initialized = False

ticker = "KXHIGHNY-26AUG20-T75"
side = "yes"

# 1. Log + fill an entry order (a genuine open position)
entry_id = el.log_order(ticker=ticker, side=side, quantity=5, price=0.40,
                         order_type="limit", status="pending", live=True)
el.log_order_result(entry_id, status="filled", fill_quantity=5)

# 2. Fully close it via a protective exit (mirrors order_executor._exit_live_position)
exit_id = el.log_order(ticker=ticker, side=side, quantity=5, price=0.30,
                        order_type="market", status="pending", live=True,
                        closes_position_id=entry_id)
el.log_order_result(exit_id, status="filled", fill_quantity=5)
position = {"id": entry_id, "quantity": 5, "entry_price": 0.40}
pnl, fully_closed = el.record_live_exit_fill(position, 5, 0.30, reason="stop_loss")
print("pnl", pnl, "fully_closed", fully_closed)

# Position is now fully closed (entry row settled_at set). Confirm no open positions remain.
print("open positions:", el.get_filled_unsettled_live_orders())

# 3. Would the bot allow a fresh entry into the SAME ticker+side right now?
print("was_recently_ordered(ticker, side, within_minutes=10):",
      el.was_recently_ordered(ticker, side, within_minutes=10))
print("was_traded_today(ticker, side):", el.was_traded_today(ticker, side))
print("was_ordered_recently(ticker, days=7):", el.was_ordered_recently(ticker, days=7))
