"""Pass 7 (Weather Semantics) reproduction.

Demonstrates that settlement_monitor.check_city_settlement()'s T-ticker
(above/below) branch locks a settlement outcome off the INSTANTANEOUS METAR
reading, not the running daily extreme -- the exact AC3 bug class that was
fixed for the sibling between-bucket branch in commit 39b1ba54 (and for
weather_markets.py's _metar_lock_in in bded3d6), but never fixed for this
branch.

check_metar_lockout() is a pure function (no network calls), so this can be
demonstrated directly without touching any live/cached weather data.

Scenario: a KXHIGH*-T85 "above 85F" market. The true daily high (reached at
2pm) was 90F -- clearly TRUE/yes for "above 85". By 6pm (inside
settlement_monitor's 5-7pm monitoring window) a cold front has dropped the
instantaneous reading to 80F, which is more than the 1.0F settlement margin
below the threshold.

settlement_monitor.py's check_city_settlement() passes only the
instantaneous current_temp_f into check_metar_lockout() for the T-ticker
branch (see line ~460), never fetch_metar_daily_extreme()'s true running
max -- so it locks a confident "no" even though the real daily high (90F)
already satisfied "above 85".
"""

import sys

sys.path.insert(0, r"C:\Users\thesa\claude kalshi\.claude\worktrees\reverent-lumiere-f79c1f")

from datetime import UTC, datetime

from metar import check_metar_lockout

# True daily high already observed at 2pm local: 90F (>> 85F threshold).
true_daily_high_f = 90.0

# Instantaneous reading at 6pm local, after a cold-frontal cooldown.
instantaneous_temp_f = 80.0

threshold_f = 85.0
margin_f = 1.0  # settlement_monitor._SETTLEMENT_MARGIN_F

obs_time = datetime(2026, 8, 17, 22, 0, tzinfo=UTC)  # 6pm America/New_York (UTC-4)

# What settlement_monitor.py's T-ticker branch ACTUALLY does:
result_using_instantaneous = check_metar_lockout(
    current_temp_f=instantaneous_temp_f,
    threshold_f=threshold_f,
    direction="above",
    obs_time=obs_time,
    city_tz="America/New_York",
    margin_f=margin_f,
)

# What it WOULD produce if fed the true running daily high instead (i.e. the
# same fix pattern already applied to the between-bucket branch and to
# weather_markets.py's _metar_lock_in):
result_using_daily_extreme = check_metar_lockout(
    current_temp_f=true_daily_high_f,
    threshold_f=threshold_f,
    direction="above",
    obs_time=obs_time,
    city_tz="America/New_York",
    margin_f=margin_f,
)

print("Using instantaneous reading (what settlement_monitor.py ACTUALLY does):")
print(f"  {result_using_instantaneous}")
print()
print("Using true running daily-high (what the between-bucket sibling fix does):")
print(f"  {result_using_daily_extreme}")
print()

assert result_using_instantaneous["locked"] is True
assert result_using_instantaneous["outcome"] == "no", (
    "expected the bug to manifest as a confident, WRONG 'no' lock"
)
assert result_using_daily_extreme["locked"] is True
assert result_using_daily_extreme["outcome"] == "yes", (
    "the true daily high correctly locks 'yes' for an 'above 85' market"
)

print(
    "CONFIRMED: with an identical scenario (true daily high 90F clearly satisfies "
    "'above 85', but a post-peak cooldown to 80F by 6pm), settlement_monitor.py's "
    "T-ticker branch locks a confident, WRONG 'no' (conf="
    f"{result_using_instantaneous['confidence']:.2f}) purely because it feeds the "
    "instantaneous reading into check_metar_lockout() instead of the running daily "
    "extreme fetch_metar_daily_extreme() already provides for the between-bucket "
    "sibling branch."
)
