---
source_file: "weather_markets.py"
type: "code"
community: "Forecast Analysis Engine"
location: "L822"
tags:
  - graphify/code
  - graphify/EXTRACTED
  - community/Forecast_Analysis_Engine
---

# date

## Connections
- [[CircuitBreaker]] - `uses` [INFERRED]
- [[ForecastCache]] - `uses` [INFERRED]
- [[KalshiClient_1]] - `uses` [INFERRED]
- [[_analyze_precip_trade()]] - `references` [EXTRACTED]
- [[_analyze_snow_trade()]] - `references` [EXTRACTED]
- [[_fetch_ensemble_precip()]] - `references` [EXTRACTED]
- [[_fetch_model_ensemble()]] - `references` [EXTRACTED]
- [[_forecast_uncertainty()]] - `references` [EXTRACTED]
- [[_metar_lock_in()]] - `references` [EXTRACTED]
- [[_time_risk()]] - `calls` [EXTRACTED]
- [[analyze_trade()]] - `calls` [EXTRACTED]
- [[batch_prewarm_ensemble()]] - `calls` [EXTRACTED]
- [[enrich_with_forecast()]] - `calls` [EXTRACTED]
- [[fetch_temperature_ecmwf()]] - `references` [EXTRACTED]
- [[fetch_temperature_nbm()]] - `references` [EXTRACTED]
- [[fetch_temperature_pirate_weather()]] - `references` [EXTRACTED]
- [[fetch_temperature_weatherapi()]] - `references` [EXTRACTED]
- [[get_ensemble_temps()]] - `references` [EXTRACTED]
- [[get_weather_forecast()]] - `references` [EXTRACTED]
- [[parse_city_date()]] - `references` [EXTRACTED]
- [[save_forecast_snapshot()]] - `calls` [EXTRACTED]

#graphify/code #graphify/EXTRACTED #community/Forecast_Analysis_Engine