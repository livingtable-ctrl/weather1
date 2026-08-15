---
source_file: "tests/test_infrastructure.py"
type: "rationale"
community: "Circuit Breaker & Session Retry Infrastructure"
location: "L227"
tags:
  - graphify/rationale
  - graphify/EXTRACTED
  - community/Circuit_Breaker__Session_Retry_Infrastructure
---

# A cached (lat, lon) -> station_id lookup must not hit the network.

## Connections
- [[test_get_obs_station_cache_hit_skips_network_call()]] - `rationale_for` [EXTRACTED]

#graphify/rationale #graphify/EXTRACTED #community/Circuit_Breaker__Session_Retry_Infrastructure