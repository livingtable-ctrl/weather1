"""Pass 7 (Weather Semantics) reproduction.

Demonstrates that weather_markets._compute_persistence_prob()'s var="min"
(LOW market) branch at days_out==0 feeds the INSTANTANEOUS current
temperature into climatology.persistence_prob(), not the true running daily
low -- the identical staleness bug commit b0f4cad2 explicitly fixed for
var="max" (HIGH markets), left unmirrored for var="min".

climatology.persistence_prob() is a pure function, so the probability-math
consequence can be shown directly without touching any live/cached data.

Scenario: a KXLOW*-B##-T60 "below 60F" LOW market. The true running daily
low, already observed at 6am local, was 52F -- comfortably below the 60F
threshold (a near-certain "yes" for "below 60"). By 6pm the instantaneous
reading has warmed to 74F (typical daytime warm-up).

_compute_persistence_prob's var="min" branch (the `else` arm at
weather_markets.py:6142-6143) uses `_live.get("temp_f")` -- 74F -- as
`current_value`, not the true 52F low that already happened, when computing
persistence_prob("below", 60.0, None, current_value).
"""

import sys

sys.path.insert(0, r"C:\Users\thesa\claude kalshi\.claude\worktrees\reverent-lumiere-f79c1f")

from climatology import persistence_prob

threshold_f = 60.0
true_daily_low_f = 52.0  # already occurred at 6am, comfortably below threshold
instantaneous_temp_f = 74.0  # 6pm reading, what _compute_persistence_prob
                              # ACTUALLY uses for var="min" at days_out=0

p_using_instantaneous = persistence_prob(
    "below", threshold_f, None, instantaneous_temp_f
)
p_using_true_low = persistence_prob("below", threshold_f, None, true_daily_low_f)

print(f"persistence_prob using instantaneous 74F (what the code ACTUALLY does): "
      f"{p_using_instantaneous:.4f}")
print(f"persistence_prob using true daily low 52F (what the var='max' fix's "
      f"reasoning would mirror): {p_using_true_low:.4f}")

assert p_using_instantaneous < 0.05, (
    "using the stale, warmed-up instantaneous reading makes 'below 60' look "
    "almost impossible"
)
assert p_using_true_low > 0.90, (
    "using the true daily low (already below threshold) makes 'below 60' "
    "look near-certain, as it actually is"
)

print()
print(
    f"CONFIRMED: identical scenario (true low 52F already clearly satisfies "
    f"'below 60', but the afternoon reading has warmed to 74F), "
    f"_compute_persistence_prob's var='min' path produces a persistence_p of "
    f"{p_using_instantaneous:.4f} (near-zero) when the true, already-realized "
    f"answer is {p_using_true_low:.4f} (near-certain). This feeds directly "
    f"into analyze_trade's blended_prob at up to 0.15 weight for real "
    f"(non-shadow) LOW-market trade pricing."
)
