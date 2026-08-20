"""
Pass 8 (Mathematics) reproduction: persistence_prob() applied to a running
daily-max value (var="max", days_out=0) after b0f4cad2's fix.

Claim under test: climatology.persistence_prob() models the outcome as a
SYMMETRIC Normal(current_value, std_dev) draw. But when current_value is
today's RUNNING DAILY MAX (as fed by weather_markets._compute_persistence_prob
since b0f4cad2, via metar.fetch_metar_daily_extreme(..., "max")), the true
final daily high is a MONOTONIC non-decreasing function of time -- it can
only be >= the current running max, never below it. So whenever the running
max already clears an "above" threshold, the true probability of the
"above" outcome is exactly 1.0 (already decided), not a symmetric-normal
tail probability.

This script calls the real function with no reimplementation, and compares
its output against the analytically-obvious ground truth for the
already-exceeded case.
"""
import sys

sys.path.insert(0, r"C:\Users\thesa\claude kalshi\.claude\worktrees\reverent-lumiere-f79c1f")

from climatology import persistence_prob

print("=== 'above' condition: running max already clears threshold ===")
for margin in [0, 1, 2, 5, 10, 15]:
    threshold = 85.0
    current_running_max = threshold + margin
    p = persistence_prob("above", threshold, None, current_running_max, std_dev=5.0)
    print(
        f"threshold={threshold}, running_max_so_far={current_running_max} "
        f"(margin=+{margin}F over threshold) -> persistence_prob={p:.4f}  "
        f"(true probability, by monotonicity, = 1.0000)"
    )

print()
print("=== 'below' condition: running max already busts the threshold ===")
for margin in [0, 1, 2, 5, 10, 15]:
    threshold = 85.0
    current_running_max = threshold + margin
    p = persistence_prob("below", threshold, None, current_running_max, std_dev=5.0)
    print(
        f"threshold={threshold}, running_max_so_far={current_running_max} "
        f"(margin=+{margin}F over threshold) -> persistence_prob={p:.4f}  "
        f"(true probability, by monotonicity, = 0.0000)"
    )

print()
print("=== Effect after the hourly path's 0.15 blend weight (line ~10213) ===")
print("blended_prob = 0.85*ens_prob + 0.15*persistence_p")
for margin in [0, 1, 2]:
    threshold = 85.0
    current_running_max = threshold + margin
    p = persistence_prob("above", threshold, None, current_running_max, std_dev=5.0)
    assert p is not None, "inputs here are always valid -- see persistence_prob's own None cases"
    ens_prob = 0.60  # arbitrary illustrative ensemble estimate
    blended_wrong = 0.85 * ens_prob + 0.15 * p
    blended_true = 0.85 * ens_prob + 0.15 * 1.0
    print(
        f"margin=+{margin}F: persistence_p={p:.4f} -> blended_prob={blended_wrong:.4f} "
        f"vs. blended_prob if persistence correctly reflected certainty={blended_true:.4f} "
        f"(delta={blended_true - blended_wrong:+.4f})"
    )
