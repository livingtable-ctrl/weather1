---
source_file: "weather_markets.py"
type: "code"
community: "Forecast Analysis Engine"
location: "L731"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Forecast_Analysis_Engine
---

# datetime

## Connections
- [[CircuitBreaker]] - `uses` [INFERRED]
- [[ForecastCache]] - `uses` [INFERRED]
- [[KalshiClient_1]] - `uses` [INFERRED]
- [[_ttl_until_next_cycle()]] - `references` [EXTRACTED]
- [[fetch_temperature_pirate_weather()]] - `calls` [EXTRACTED]
- [[time_decay_edge()]] - `references` [EXTRACTED]
- [[weather_markets.py]] - `imports_from` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Forecast_Analysis_Engine