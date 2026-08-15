---
source_file: "tests/test_forecast_cache.py"
type: "code"
community: "Forecast Persistent Cache"
location: "L391"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Forecast_Persistent_Cache
---

# test_dump_to_disk_raises_on_per_entry_ttl_entry()

## Connections
- [[PersistentForecastCache]] - `calls` [EXTRACTED]
- [[_tuple_key_to_str()]] - `indirect_call` [INFERRED]
- [[dump_to_disk must refuse (not silently drop the TTL) when the cache holds an…]] - `rationale_for` [EXTRACTED]
- [[test_forecast_cache.py]] - `contains` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Forecast_Persistent_Cache