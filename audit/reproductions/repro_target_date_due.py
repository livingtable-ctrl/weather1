import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
import main

# AUD-0017 fix verification (batch-07, 2026-08-21): _target_date_due's
# signature changed from (target_date_str, today_date) to
# (target_date_str, city) -- it now self-computes city-local "today"
# internally via ZoneInfo instead of taking a precomputed date. This script
# no longer reproduces a bug (the bug is fixed); it demonstrates the fixed
# behavior at the same evening-window instant the original repro used.
#
# Simulate: real time is 01:00 UTC Aug 18 (=21:00 EDT Aug 17, still evening
# of Aug 17 in New York local time). UTC "today" has rolled to Aug 18 but
# NY local "today" is still Aug 17.
fixed_instant = datetime(2026, 8, 18, 1, 0, tzinfo=UTC)


class _FixedDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        if tz is None:
            return fixed_instant.replace(tzinfo=None)
        return fixed_instant.astimezone(tz)


# A paper trade whose target_date is TOMORROW in NY-local terms (Aug 18) --
# should NOT be "due" yet since NY local today is still Aug 17.
target_date_str = "2026-08-18"

with patch("main.datetime", _FixedDatetime):
    result_nyc = main._target_date_due(target_date_str, "NYC")
    # LA (PDT, UTC-7) is further behind UTC than NYC (EDT, UTC-4) -- also
    # not due, and for a stronger margin.
    result_la = main._target_date_due(target_date_str, "LA")

print("target_date =", target_date_str)
print(f"at {fixed_instant.isoformat()} (UTC already rolled to Aug 18):")
print(f"  city=NYC -> due={result_nyc}  (expected False -- NY-local is still Aug 17)")
print(f"  city=LA  -> due={result_la}  (expected False -- LA-local is still Aug 17)")

if result_nyc or result_la:
    print("\nFAIL: fix regressed -- a city-local comparison should not be due yet.")
    sys.exit(1)
print("\nOK: fix verified -- neither city reads as due during the UTC rollover window.")
