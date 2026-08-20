import sys

sys.path.insert(0, r"C:\Users\thesa\claude kalshi\.claude\worktrees\reverent-lumiere-f79c1f")

# Simulate the floor-clip line directly: shifted = [max(0.0, s + shift) for s in remaining_sums]
remaining_sums = [0.0]*12 + [1.0, 2.0, 3.0]  # mostly zeros (dry tail), a few wet days

def apply_shift(sums, shift):
    return [max(0.0, s + shift) for s in sums]

dry_shift = -0.8
wet_shift = 0.8

dry_out = apply_shift(remaining_sums, dry_shift)
wet_out = apply_shift(remaining_sums, wet_shift)

mean_before = sum(remaining_sums)/len(remaining_sums)
mean_dry = sum(dry_out)/len(dry_out)
mean_wet = sum(wet_out)/len(wet_out)

dry_delta = mean_dry - mean_before   # should be > dry_shift (under-applied, i.e. less negative)
wet_delta = mean_wet - mean_before   # should equal wet_shift exactly (no zeros clipped on wet side... but wet_out already >0 so no clipping)

print("mean_before", mean_before)
print("mean_dry", mean_dry, "actual applied delta", dry_delta, "vs intended", dry_shift)
print("mean_wet", mean_wet, "actual applied delta", wet_delta, "vs intended", wet_shift)

assert abs(dry_delta) < abs(dry_shift), "dry shift should be under-applied (clipped)"
assert abs(wet_delta - wet_shift) < 1e-9, "wet shift should apply in full (no clipping, since it only ever raises values)"
print("CONFIRMED: floor clip asymmetrically under-applies negative (dry) shift vs positive (wet) shift")
