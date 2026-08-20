"""
Pass 4 (Feature Correctness) reproduction.

Demonstrates that settlement_monitor._check_between_settlement() can lock
YES using the INSTANTANEOUS current_temp_f as the deciding value even
though the authoritative running daily extreme (max_temp_f, from
metar.fetch_metar_daily_extreme()) is still BELOW the band -- i.e. the
temperature has only just this instant entered the band and may still be
rising, which is exactly the "still-evolving trajectory" scenario the
between-bucket lock-in feature exists to avoid locking on prematurely.

This contradicts the function's own docstring claim: "YES only from a
REAL max_temp_f; never locks YES from the current_temp_fallback alone".
"""
import sys

sys.path.insert(0, ".")

from settlement_monitor import _check_between_settlement

# Bucket: 66.5 - 68.5 (a realistic 2F between-bucket band)
lower_f = 66.5
upper_f = 68.5

# max_temp_f (the "authoritative" running daily high per
# fetch_metar_daily_extreme(), independently cached and possibly a few
# minutes stale) is still BELOW the band -- the true confirmed running high
# has not reached the band yet.
max_temp_f = 65.0

# current_temp_f (the freshest instantaneous reading, from a separately
# cached fetch_metar() call) has just now risen INTO the band. Nothing
# confirms this is the day's peak -- the temperature could still be rising.
current_temp_f = 67.0

result = _check_between_settlement(current_temp_f, lower_f, upper_f, max_temp_f)
print("Result:", result)

assert result["locked"] is True, "expected a lock to reproduce the issue"
assert result["outcome"] == "yes"
# comp_temp_f used for the decision equals current_temp_f, NOT max_temp_f --
# i.e. the "REAL max_temp_f" guard is bypassed by the max() combination.
assert result["comp_temp_f"] == current_temp_f
print(
    "\nCONFIRMED: locked YES using comp_temp_f == current_temp_f "
    f"({current_temp_f}) even though the authoritative max_temp_f "
    f"({max_temp_f}) is still BELOW the band lower edge ({lower_f}) -- "
    "the docstring's 'never locks YES from the current-temp fallback "
    "alone' guarantee does not hold when current_temp_f > max_temp_f."
)
