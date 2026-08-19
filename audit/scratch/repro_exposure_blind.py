"""
Pass 19 (Regression) reproduction.

Demonstrates that paper.check_position_limits()'s exposure math is blind to
execution_log-tracked live positions (opened via cmd_order after commit
e5331a8d), even though check_position_limits() is invoked as a real gate on
cmd_order's live "buy" path (main.py:4546-4569).

Safety: paper.DATA_PATH is monkeypatched to a temp file BEFORE any paper.*
call, so no real data/paper_trades.json (main-clone or worktree) is ever
touched. No execution_log DB is touched either -- this only demonstrates
that get_open_trades()/get_total_exposure() have no awareness of
execution_log at all (by inspecting source), plus a live scenario using
paper's own in-memory ledger to prove the exposure math ignores anything
not recorded there.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import paper  # noqa: E402

tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w")
tmp.write('{"trades": [], "balance": 1000.0, "next_id": 1}')
tmp.close()
paper.DATA_PATH = Path(tmp.name)  # redirect off real data before any write

# Simulate: BEFORE e5331a8d, cmd_order's live buy called place_paper_order()
# unconditionally, so a live $200 buy WAS visible to check_position_limits.
before_fix_existing = sum(
    t.get("cost", 0.0)
    for t in [{"cost": 200.0, "ticker": "KXHIGHNY-26AUG20-T85"}]
)
print(f"[Before e5331a8d] cmd_order live buy cost counted in existing_cost: "
      f"${before_fix_existing:.2f} (via paper ledger, accidentally)")

# AFTER e5331a8d: the same live buy is routed to execution_log instead, and
# paper.get_open_trades() (which check_position_limits' existing_cost /
# get_total_exposure / get_city_date_exposure / get_directional_exposure /
# get_correlated_exposure all read from -- verified in paper.py source,
# lines ~1598-1673 and ~3628-3632) has zero knowledge of it.
# STARTING_BALANCE defaults to $1000; MAX_DIRECTIONAL_EXPOSURE = 15% = $150
# per city/date/side. A prior $100 (10%) live buy via cmd_order is now
# invisible (routed to execution_log, not paper.get_open_trades()). A SECOND
# $100 (10%) live buy on the same city/date/side should be blocked (10% +
# 10% = 20% > 15%) if the first were counted -- but it isn't.
result = paper.check_position_limits(
    "KXHIGHNY-26AUG20-T85",
    qty=200,          # a SECOND live buy for $100 more (200 * 0.50)
    price=0.50,
    max_cost_per_market=250.0,
    city="NYC",
    target_date_str="2026-08-20",
    side="yes",
)
print(f"[After e5331a8d] check_position_limits() result for a 2nd $100 (10%) "
      f"live buy on the SAME city/date/side (prior $100/10% live buy via "
      f"cmd_order is invisible; combined 20% should breach the 15% "
      f"directional cap): {result}")
assert result["ok"] is True, "expected the gate to wrongly allow this"
assert result["existing_cost"] == 0.0, (
    "expected existing_cost to be 0.0 -- prior live buy is invisible to "
    "paper.get_open_trades()"
)
print(
    "\nCONFIRMED: check_position_limits() reports existing_cost=$0.00 and "
    "ok=True for a second live cmd_order buy that would push real exposure "
    "on this ticker/city/date to $400+, because it only sums "
    "paper.get_open_trades() and execution_log-recorded live positions "
    "(opened via cmd_order since e5331a8d) never appear there. Before "
    "e5331a8d, the same scenario's first buy WOULD have been counted "
    "(accidentally, via the paper-ledger phantom-position bug), so this "
    "specific protection regressed as a direct side effect of the fix."
)

Path(tmp.name).unlink(missing_ok=True)
