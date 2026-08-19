"""Repro: a live pending order can be silently evicted from
_poll_pending_orders'/_count_open_live_orders' visibility window once
enough OTHER orders (paper trades interleaved in the same `orders` table)
are logged afterward -- both functions call execution_log.get_recent_orders(
limit=N) (ORDER BY placed_at DESC LIMIT N, no `live` filter in SQL) and only
filter for live+pending in Python AFTER truncating to the N most recent rows
of ANY kind.
"""
import sys, tempfile, pathlib, time
sys.path.insert(0, r"C:\Users\thesa\claude kalshi\.claude\worktrees\reverent-lumiere-f79c1f")
import execution_log as el

tmpdir = tempfile.mkdtemp()
el.DB_PATH = pathlib.Path(tmpdir) / "execution_log_test3.db"
el._initialized = False

# 1. A live GTC order gets placed and is genuinely still resting (pending).
live_id = el.log_order(ticker="KXHIGHNY-26AUG20-T75", side="yes", quantity=5,
                        price=0.40, order_type="limit", status="pending",
                        live=True, response={"order_id": "abc123"})

# 2. Simulate paper-trading volume: 250 more orders get logged into the SAME
#    `orders` table afterward (e.g. ~5 paper fills/cycle x 50 cycles = a
#    little over 4 hours of `watch --auto` at its 300s REFRESH_SECS cadence).
for i in range(250):
    pid = el.log_order(ticker=f"KXHIGHNY-26AUG20-T{i}", side="yes", quantity=1,
                        price=0.30, order_type="market", status="pending", live=False)
    el.log_order_result(pid, status="filled", fill_quantity=1)

# 3. Reproduce _poll_pending_orders' exact selection logic (order_executor.py:439-443)
pending_visible_200 = [
    o for o in el.get_recent_orders(limit=200)
    if o.get("live") and o.get("status") == "pending" and o.get("response")
]
print("live pending order visible to _poll_pending_orders (limit=200)?",
      any(o["id"] == live_id for o in pending_visible_200))

# 4. Reproduce _count_open_live_orders' exact selection logic (order_executor.py:172-175)
count_500 = sum(1 for o in el.get_recent_orders(limit=500)
                 if o.get("live") and o.get("status") == "pending")
print("live pending order counted by _count_open_live_orders (limit=500) after 250 interleaved paper orders?",
      count_500 >= 1, "(count =", count_500, ")")

# 5. Push past 500 total interleaved orders to show the count gate itself also drops to 0.
for i in range(250, 520):
    pid = el.log_order(ticker=f"KXHIGHNY-26AUG20-T{i}", side="yes", quantity=1,
                        price=0.30, order_type="market", status="pending", live=False)
    el.log_order_result(pid, status="filled", fill_quantity=1)

count_500_later = sum(1 for o in el.get_recent_orders(limit=500)
                        if o.get("live") and o.get("status") == "pending")
print("live pending order counted by _count_open_live_orders after 520 interleaved paper orders?",
      count_500_later >= 1, "(count =", count_500_later, ")")

# The order genuinely never disappeared from the DB -- it is still there and still pending.
row = el.get_order_by_id(live_id)
print("row still exists in DB with status:", row["status"] if row else None)
