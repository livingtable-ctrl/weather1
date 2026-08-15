---
source_file: "tests/test_forecast_cache.py"
type: "code"
community: "Forecast Persistent Cache"
location: "L405"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Forecast_Persistent_Cache
---

# test_load_from_disk_does_not_evict_beyond_max_size()

## Connections
- [[PersistentForecastCache]] - `calls` [EXTRACTED]
- [[Regression load_from_disk must restore the ENTIRE persisted snapshot even if…]] - `rationale_for` [EXTRACTED]
- [[_tuple_key_to_str()]] - `indirect_call` [INFERRED]
- [[_tuple_str_to_key()]] - `indirect_call` [INFERRED]
- [[test_forecast_cache.py]] - `contains` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Forecast_Persistent_Cache