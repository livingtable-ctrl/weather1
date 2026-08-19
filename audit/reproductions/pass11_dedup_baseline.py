import os, sys, tempfile, pathlib
tmpdir = tempfile.mkdtemp()
sys.path.insert(0, r"C:\Users\thesa\claude kalshi\.claude\worktrees\reverent-lumiere-f79c1f")
import execution_log as el
el.DB_PATH = pathlib.Path(tmpdir) / "execution_log_test2.db"
el._initialized = False

ticker = "KXHIGHNY-26AUG20-T75"
side = "yes"
entry_id = el.log_order(ticker=ticker, side=side, quantity=5, price=0.40,
                         order_type="limit", status="pending", live=True)
el.log_order_result(entry_id, status="filled", fill_quantity=5)
# NO exit row logged at all -- baseline: does the entry fill alone already trip the guards?
print("was_traded_today (entry only, no exit row):", el.was_traded_today(ticker, side))
print("was_recently_ordered (entry only):", el.was_recently_ordered(ticker, side, within_minutes=10))
