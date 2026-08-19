import sys, datetime
sys.path.insert(0, r"C:\Users\thesa\claude kalshi\.claude\worktrees\reverent-lumiere-f79c1f")
import main

# Simulate: real time is 01:00 UTC Aug 18 (=21:00 EDT Aug 17, still evening
# of Aug 17 in New York local time). UTC "today" has rolled to Aug 18 but
# NY local "today" is still Aug 17.
utc_today = datetime.date(2026, 8, 18)
ny_local_today = datetime.date(2026, 8, 17)

# A paper trade whose target_date is TOMORROW in NY-local terms (Aug 18) --
# should NOT be "due" yet since NY local today is still Aug 17.
target_date_str = "2026-08-18"

result_using_utc_today = main._target_date_due(target_date_str, utc_today)
result_using_local_today = main._target_date_due(target_date_str, ny_local_today)

print("target_date =", target_date_str)
print("compared against UTC-today (%s)  -> due=%s" % (utc_today, result_using_utc_today))
print("compared against NY-local-today (%s) -> due=%s" % (ny_local_today, result_using_local_today))
