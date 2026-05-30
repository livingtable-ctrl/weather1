---
source_file: "weather_markets.py"
type: "code"
community: "Module: tests"
location: "L2704"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Module_tests
---

# is_stale()

## Connections
- [[.test_market_no_volume_closing_soon_is_stale()]] - `calls` [EXTRACTED]
- [[.test_market_no_volume_far_future_not_stale()]] - `calls` [EXTRACTED]
- [[.test_market_with_open_interest_not_stale()]] - `calls` [EXTRACTED]
- [[.test_market_with_volume_not_stale()]] - `calls` [EXTRACTED]
- [[.test_missing_close_time_not_stale()]] - `calls` [EXTRACTED]
- [[Returns True if a market has no volume AND closes within 60 minutes.     Stale]] - `rationale_for` [EXTRACTED]
- [[bool_24]] - `references` [EXTRACTED]
- [[test_paper.py]] - `imports` [EXTRACTED]
- [[weather_markets.py]] - `contains` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Module_tests