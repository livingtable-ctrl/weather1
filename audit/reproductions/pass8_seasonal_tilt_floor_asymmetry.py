"""
Pass 8 (Mathematics) reproduction: acis_precip.apply_seasonal_tilt()'s
max(0.0, s + shift) floor, applied to a short far-tail window
(d190d09d's new call site: 1-3 day tails, mostly exact zeros).

Claim under test (already flagged in d190d09d's own commit message as an
"accepted, documented limitation"): the floor at 0.0 makes a DRY tilt
(shift < 0) systematically under-applied relative to a WET tilt (shift > 0)
of the same magnitude, because most historical tail-window sums are exactly
0.0 (no rain in a 1-3 day window) and can't go negative.

This script calls the real acis_precip.apply_seasonal_tilt() function
(no reimplementation) on a synthetic but realistic short-tail sample and
compares the realized mean shift against the nominal (undamped-by-floor)
damped_shift_in the function computes internally.
"""
import sys

sys.path.insert(0, r"C:\Users\thesa\claude kalshi\.claude\worktrees\reverent-lumiere-f79c1f")

from acis_precip import apply_seasonal_tilt

# Realistic 2-day tail window: out of 20 historical years, most have zero
# rain in this specific 2-day window; a few have some.
tail_sums_2day = [0.0] * 15 + [0.05, 0.10, 0.20, 0.30, 0.45]
# full_month_sums: 20 years of full-month totals (used only for the ratio).
full_month_sums = [2.0 + 0.1 * i for i in range(20)]

print("tail_sums (2-day window):", tail_sums_2day)
mean_before = sum(tail_sums_2day) / len(tail_sums_2day)
print(f"mean(tail_sums) before tilt = {mean_before:.4f}")

print()
print("=== WET tilt (SEAS5 forecasts wetter than climatology) ===")
# seasonal_mean_mm set so ratio = 1.5 (wetter), clamped to 2.0 max.
clim_full_month_mean_in = sum(full_month_sums) / len(full_month_sums)
clim_full_month_mean_mm = clim_full_month_mean_in * 25.4
seasonal_mean_wet = clim_full_month_mean_mm * 1.5
shifted_wet, applied_wet = apply_seasonal_tilt(
    tail_sums_2day, full_month_sums, seasonal_mean_wet
)
mean_after_wet = sum(shifted_wet) / len(shifted_wet)
print(f"applied={applied_wet}, shifted tail_sums={shifted_wet}")
print(f"mean before={mean_before:.4f} -> mean after={mean_after_wet:.4f}  "
      f"(realized mean shift = {mean_after_wet - mean_before:+.4f})")

print()
print("=== DRY tilt (SEAS5 forecasts drier than climatology, same magnitude ratio) ===")
seasonal_mean_dry = clim_full_month_mean_mm * (1 / 1.5)
shifted_dry, applied_dry = apply_seasonal_tilt(
    tail_sums_2day, full_month_sums, seasonal_mean_dry
)
mean_after_dry = sum(shifted_dry) / len(shifted_dry)
print(f"applied={applied_dry}, shifted tail_sums={shifted_dry}")
print(f"mean before={mean_before:.4f} -> mean after={mean_after_dry:.4f}  "
      f"(realized mean shift = {mean_after_dry - mean_before:+.4f})")

print()
wet_shift = mean_after_wet - mean_before
dry_shift = mean_after_dry - mean_before
print(f"|wet shift| = {abs(wet_shift):.4f}   |dry shift| = {abs(dry_shift):.4f}")
print(f"Asymmetry ratio (wet/dry magnitude) = {abs(wet_shift) / abs(dry_shift):.2f}x"
      if dry_shift != 0 else "dry shift is exactly 0 (fully floored)")

print()
print("=== Effect on exceedance probability (combined_totals threshold check) ===")
# Simulate: near-forecast members are all e.g. 0.9 inches (near member fetch),
# threshold - month_to_date_actual = 1.0 inch (i.e. need the tail to add >0.1in)
near_members = [0.9] * 30
threshold_margin = 1.0  # need near+tail > this

def exceed_frac(tail_vals):
    combined = [m + t for m in near_members for t in tail_vals]
    return sum(1 for c in combined if c > threshold_margin) / len(combined)

print(f"exceed_frac with UNTILTED tail = {exceed_frac(tail_sums_2day):.4f}")
print(f"exceed_frac with WET-tilted tail = {exceed_frac(shifted_wet):.4f}")
print(f"exceed_frac with DRY-tilted tail = {exceed_frac(shifted_dry):.4f}")
