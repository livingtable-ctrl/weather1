import sys

sys.path.insert(0, r"C:\Users\thesa\claude kalshi\.claude\worktrees\reverent-lumiere-f79c1f")
from settlement_monitor import _check_between_settlement

# Case from finding: current has risen into band, max_temp_f (authoritative) still below band
r = _check_between_settlement(current_temp_f=67.0, lower_f=66.5, upper_f=68.5, max_temp_f=65.0)
print("case1 (current above band-lower, max below band):", r)
assert r["locked"] is True and r["outcome"] == "yes" and r["comp_temp_f"] == 67.0, r

# Sanity: with max_temp_f=None entirely (existing test's case) -> not locked
r2 = _check_between_settlement(current_temp_f=69.5, lower_f=69.5, upper_f=71.5, max_temp_f=None)
print("case2 (max_temp_f=None):", r2)
assert r2["locked"] is False

print("CONFIRMED: YES lock decided by current_temp_f when max_temp_f present-but-lower")
