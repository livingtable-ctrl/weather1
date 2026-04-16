# Research Findings: External Systems & Improvement Ideas

**Last updated:** 2026-04-16  
**Purpose:** Compiled research from similar Kalshi trading bots, weather forecasting APIs, academic papers, and prediction market strategies. Use this as a reference for future development.

---

## Part 1 — Similar Open-Source Systems Found

### 1. suislanchez/polymarket-kalshi-weather-bot
- Closest direct analog: trades KXHIGH series on Kalshi + Polymarket simultaneously
- Uses 31-member GFS ensemble + BTC microstructure signals
- **Edge threshold:** 8% for weather, 2% for BTC microstructure
- **Position sizing:** 15% fractional Kelly, max 5% bankroll, $100 hard cap per trade
- React dashboard, FastAPI backend, SQLite
- Implements RSI(14), VWAP deviation, SMA crossover on Kalshi order book for market microstructure signals

### 2. OctagonAI/kalshi-deep-trading-bot
- AI-native CLI with a **5-gate sequential risk engine**: Kelly → Liquidity → Correlation → Concentration → Drawdown
- Half-Kelly default, external AI probability API
- Each gate independently vetoes a trade — formalized pipeline vs. our single _validate_trade_opportunity

### 3. braedonsaunders/homerun
- Full prediction market platform: 25+ strategies, 39 data source presets
- **Walk-forward backtesting** with parameter grid search
- A/B experiment framework — runs variants in parallel with capped exposure, auto-disables underperformers
- **VPIN toxicity detection** (Volume-synchronized Probability of Informed Trading)
- Whale copy trading, insider detection (27-point scoring)
- Tiered market scanning: HOT/WARM/COLD scan frequencies
- **Settlement lag strategy**: buy when outcome is known but price hasn't updated yet
- Flash crash circuit breaker per market (price moves >X% in short window = cooldown)

### 4. yllvar/Kalshi-Quant-TeleBot
- GARCH volatility modeling, cointegration-based statistical arbitrage
- Real-time Telegram interface for trade notifications and emergency stops
- 10-position cap, daily 2% loss cap

### 5. ImMike/polymarket-arbitrage
- Scans 10,000+ markets for cross-platform Kalshi/Polymarket pricing gaps
- Same weather event sometimes trades on both platforms at different prices

### 6. Weather Edge MCP (RJW34 / kalshiweatheredge.com)
- City-specific NWS bias correction: Miami -3°F, NYC -1°F, Denver -2 to -4°F
- METAR aviation observations as third data layer
- Adaptive model weighting based on ensemble spread agreement
- Confidence tiers: HIGH (models agree within 10%, EV >5¢), MODERATE (within 20%), LOW

### 7. evan-kolberg/prediction-market-backtesting
- NautilusTrader fork with Kalshi/Polymarket adapters
- Proper historical backtesting infrastructure for prediction markets

---

## Part 2 — Data Sources

### Currently in the Bot
- Open-Meteo GFS seamless ensemble
- Open-Meteo ICON seamless
- NWS api.weather.gov point forecasts

### HIGH PRIORITY: Missing Data Sources

#### NOAA MOS (Model Output Statistics)
**Why:** MOS is post-processed specifically for ASOS airport stations — the same stations Kalshi settles on. More accurate than raw gridded NWP for this use case. Trained on historical station observations (not interpolated grid cells).

- **GFS MOS (MAV):** Updated 4x/day (00/06/12/18Z), valid 6–72 hours
- **Extended MOS (MEX):** Updated 2x/day, valid 24–192 hours
- **GEFS Ensemble MOS:** Also available
- **Free API via Iowa State (IEM):**
  - JSON: `https://mesonet.agron.iastate.edu/api/1/mos.json?station=KJFK&model=GFS`
  - CSV: `https://mesonet.agron.iastate.edu/api/1/mos.txt?station=KJFK&model=GFS`
  - Archive back to May 3, 2007
- **Raw bulletins:** `https://www.nws.noaa.gov/mdl/synop/products.php`

#### LAMP (Localized Aviation MOS Program)
- Hourly-updated MOS (vs 6-hourly for standard MOS)
- 2,000+ stations, 38-hour window
- `https://vlab.noaa.gov/web/mdl/lamp`

#### National Blend of Models (NBM)
**Why:** NWS's official blended probabilistic product combining GFS + HRRR + ECMWF + GEFS + NAM. Provides direct percentile outputs (e.g., "NBM90Pct = 10% chance temp exceeds X"). Already calibrated and blended by NWS.

- Free on AWS: `https://registry.opendata.aws/noaa-nbm/`
- Updated hourly

#### METAR / Aviation Weather (Real-Time Observations)
**Why:** After ~2 PM local time, METAR readings from the exact settlement station lock in what the daily high already is. Reported 85–90% win rate for same-day trades when temp has clearly peaked.

- **Free API (NOAA Aviation Weather Center):** `https://aviationweather.gov/api/data/metar?ids=KJFK&format=json`
  - 100 requests/minute, 15-day history, completely free
- **IEM ASOS archive:** `https://mesonet.agron.iastate.edu/request/download.phtml`
- **Synoptic Data API:** Paid, 99.99% uptime SLA, 170,000+ stations

#### ECMWF AIFS Ensemble
**Why:** 51-member AI ensemble. Became operational July 1, 2025. Outperforms physics-based IFS by up to 20% on surface temperature.

- **Python package:** `pip install ecmwf-opendata`
- **Access:** `from ecmwf.opendata import Client; c = Client(source="ecmwf")`
- **Herbie library:** `pip install herbie-data` — single library for GFS, HRRR, ECMWF IFS, AIFS, NBM
- **Open-Meteo:** Available via ECMWF API endpoint (6-hourly time steps)
- Free under CC-BY 4.0, rolling archive of last ~2-3 days

#### Herbie Python Library
- Single unified download library for GFS, HRRR, RAP, ECMWF IFS, AIFS, NBM, ICON from NOMADS/AWS/Azure/Google
- `pip install herbie-data`
- Simplifies multi-model data pipeline significantly

### MEDIUM PRIORITY

#### Cross-Platform Prices (Polymarket)
- Same weather events sometimes trade on both Kalshi and Polymarket at different prices
- Buying YES on one + NO on the other below $1.00 combined = risk-free arb (when settlement definitions match)
- Weather markets lower settlement risk than political markets (both reference NWS data)

#### minuteTemp.com
- Purpose-built for Kalshi/Polymarket weather traders
- REST + WebSocket APIs updating every 60 seconds from METAR/ASOS
- Integrates GFS, HRRR, ECMWF, NAM, NBM, ICON in one view
- Paid service

### Tomorrow.io / ClimaCell
- Proprietary microweather tech, minute-level forecasts
- **Not recommended for this use case:** Uses proprietary gridded forecasts, not station-specific MOS. Not calibrated for ASOS airport stations. Better for general weather apps than Kalshi settlement prediction.

---

## Part 3 — Critical Settlement Mechanics

### NYC Settles on Central Park (KNYC), NOT JFK
**⚠️ Known systematic error trap.** Kalshi NYC high-temp markets settle on the NWS CLI from Central Park (KNYC), not JFK (KJFK) or LaGuardia (KLGA). NWS gridpoint forecasts and most weather APIs forecast for the metro area centroid, which runs **1–3°F warmer** than Central Park due to:
- Different urban heat island characteristics
- Different terrain
- Different station exposure

**Impact:** Any code using JFK or generic NYC coordinates for probability calculation has a systematic warm bias that costs edge on every NYC trade.

### Settlement Timing Details
- Kalshi resolves contracts **6–9 AM ET** the morning after the observation day
- Settlement source is **exclusively the NWS Daily Climatological Report (CLI)**, not real-time METAR or weather apps
- CLI uses 1-minute raw ASOS sensor data; NWS reviews for faulty sensors
- During DST: reporting period is Local Standard Time (midnight to midnight), so the "day" effectively runs 1 AM to 12:59 AM the next day — matters for overnight temperature drops

### CLI Direct Access
- NYC: `https://tgftp.nws.noaa.gov/data/raw/cd/cdus41.kokx.cli.nyc.txt`
- NWS product page: `https://forecast.weather.gov/product.php?site=NWS&issuedby=NYC&product=CLI`

### Known Station-Level Biases
| City | Station | Known Bias |
|------|---------|-----------|
| New York | KNYC (Central Park) | NWS gridpoint overshoots by ~1°F (warm) |
| Miami | KMIA | NWS gridpoint overshoots by ~3°F (warm) |
| Denver | KDEN | Mountain terrain introduces 2–4°F uncertainty |
| General GFS | All | Positive warm bias for southern cities |
| HRRR | All | Nighttime cold bias at urban sites; daytime warm bias at rural |
| ECMWF | All | ~0.5–1.0°F MAE advantage vs GFS for days 1–3 |

---

## Part 4 — Strategies

### S1. METAR Lock-In (Same-Day Trades)
After ~2 PM local time, if METAR shows the temperature has already peaked well below (or above) the market threshold, the outcome is nearly certain.
- **Reported win rate:** 85–90%
- **Signal:** Current temp + rate of change + time of day
- **Risk:** Sensor corrections can change final CLI reading; occasional late-day temperature spikes

### S2. Per-City Systematic Bias Correction
Apply station-specific correction terms to model output before computing probability:
- Simple linear regression on 6+ months of (model_forecast → actual_CLI_high) is sufficient
- Even a fixed offset (e.g., subtract 1°F from all NYC forecasts) captures most systematic error
- More sophisticated: per-city, per-season, per-lead-time correction table
- **Free training data:** UCI ML Repository: `https://archive.ics.uci.edu/dataset/514/`

### S3. Confidence-Tiered Edge Thresholds
Instead of a single edge threshold, use tiers:
| Confidence Level | Condition | Minimum Edge |
|-----------------|-----------|-------------|
| HIGH | Models agree within 10%, EV > 5¢ | 5% |
| MODERATE | Models agree within 20% | 7% |
| LOW | Model divergence present | 10% |

### S4. Ensemble Spread as Timing Signal
- High ensemble spread = high forecast uncertainty → wait for convergence before entering
- Narrowing spread ahead of market expiry = good time to enter
- Spread-skill ratio (CRPS decomposition) formalizes this as a calibration metric

### S5. Settlement Lag Exploitation
The window between when METAR/DSM preliminary readings confirm the outcome and when the official CLI report publishes. Market prices may not have fully updated. A monitoring loop that checks METAR every few minutes after 5 PM local time can catch this.

### S6. Statistical Arbitrage — Correlated City Pairs
Chicago + Milwaukee, NYC + Boston, Dallas + Houston temperature markets are correlated by regional weather patterns. When one city's market is mispriced relative to the other (given the same weather system), there may be a relative value trade.

### S7. Cross-Platform Arbitrage (Kalshi ↔ Polymarket)
When the same weather event trades on both platforms, buying YES on one and NO on the other below $1.00 combined locks in risk-free profit. Requires monitoring both order books simultaneously.

### S8. Gaussian Distribution Method
Instead of raw ensemble fraction counting, model P(T > threshold) using a Gaussian:
- Mean = ensemble mean forecast
- Sigma = historical RMSE for that city/station/lead-time combination
- More principled than counting members, especially at short lead times where ensemble spread underestimates uncertainty

---

## Part 5 — Risk Management Ideas

### R1. 5-Gate Sequential Risk Engine (from OctagonAI)
Replace single `_validate_trade_opportunity` with sequential independent gates:
1. Kelly sizing gate
2. Liquidity depth gate
3. Correlation exposure gate
4. Concentration limit gate
5. Drawdown guard gate

Each gate independently vetoes the trade and logs its reason.

### R2. Drawdown-Tiered Kelly Fraction Reduction
| Drawdown Level | Kelly Multiplier |
|---------------|-----------------|
| 0 – 10% | 0.5x (current) |
| 10 – 20% | 0.25x |
| 20%+ | 0.1x (survival mode) |

### R3. Per-Market Flash Crash Circuit Breaker
If a specific market's price moves >X% in a short window (e.g., >20% in 5 minutes), put that market in cooldown. Prevents entering on a flash-crashed price. Separate from our existing data-source circuit breakers.

### R4. Hard Per-Trade Dollar Cap (Separate from Kelly)
Kelly can suggest a large position; a hard dollar cap prevents single-trade overexposure regardless of bankroll size. Standard across all reviewed bots: $75–$100 per trade cap.

### R5. KL Divergence Calibration Health Metric
Track KL divergence between predicted probability distribution and observed outcome frequencies per city/season. High KL divergence = model is miscalibrated for that city/season → reduce position size or pause trading.
- **Why it matters:** Probability calibration errors reduce portfolio growth linearly; Kelly fraction errors reduce it quadratically. Miscalibration is more dangerous than position sizing errors.

### R6. Settlement Ambiguity Pre-Trade Check
Flag markets within N hours of a contested preliminary reading (when METAR diverges significantly from model forecast near end of day). Reduces exposure to ambiguous settlements.

---

## Part 6 — Execution Improvements

### E1. Kalshi WebSocket API (Real-Time Order Book)
**Production URL:** `wss://api.elections.kalshi.com/trade-api/ws/v2`

**⚠️ March 12, 2026 API Migration:** Prices now expressed as dollar strings with 4 decimal places (`"0.6500"`). Use `yes_dollars_fp` and `no_dollars_fp` fields — NOT legacy integer cents fields. Check that current code handles this correctly.

**Channels:** `orderbook_delta`, `ticker`, `trade`, `fill`
**Flow:** First message = full `orderbook_snapshot`, subsequent = `orderbook_delta`

**Authentication:** RSA-PSS signature on:
- `KALSHI-ACCESS-KEY`
- `KALSHI-ACCESS-SIGNATURE` (sign: `timestamp + "GET" + "/trade-api/ws/v2"`)
- `KALSHI-ACCESS-TIMESTAMP`

### E2. Maker-Mode Limit Orders
Place limit orders at mid-price instead of hitting the ask. Passive (maker) orders pay lower fees on Kalshi. At thin edges, fee drag is material.

### E3. Tiered Market Scanning Frequency
| Tier | Condition | Scan Frequency |
|------|-----------|---------------|
| HOT | High volume, active | Every few seconds |
| WARM | Normal activity | Every minute |
| COLD | Low activity, far out | Every 5–10 minutes |

Reduces API rate limit consumption and focuses compute on active markets.

### E4. Order Fill Timeout Management
Track open limit orders. Cancel and reassess if unfilled after a configurable timeout. Stale limit orders sitting in the book during adverse market moves create unintended exposure.

---

## Part 7 — Monitoring & Analytics

### M1. Reliability Diagram (Calibration Curve)
Plot forecast probability bins (0-10%, 10-20%, ..., 90-100%) against observed win frequencies. If your model says 70% but wins 80% of the time, apply a correction. Visually shows over/under-confidence. Add to Flask dashboard.

### M2. CRPS (Continuous Ranked Probability Score)
Better than Brier score for the underlying temperature probability distribution. Decomposes into:
- **Reliability:** Is the ensemble spread correct?
- **Resolution:** Can the model discriminate outcomes?
- **Uncertainty:** Irreducible noise

Python package: `pip install properscoring`

### M3. Per-City Per-Season Performance Segmentation
Track Brier score, edge realized vs. predicted, and win rate broken down by city AND season. NWS model biases are both city-specific and seasonally structured. Reveals which city-season combinations have true edge.

### M4. Walk-Forward Backtesting
Train on months 1–6, test on month 7, roll forward one month, repeat. Only valid backtesting approach for non-stationary weather markets. `evan-kolberg/prediction-market-backtesting` has a NautilusTrader fork with Kalshi adapters.

### M5. Strategy P&L Attribution
Track which portion of profit/loss came from each signal source:
- Ensemble spread signal
- Bias correction
- METAR lock-in
- MOS forecast
- Market microstructure

### M6. Telegram Alerting
Real-time trade notifications, parameter adjustment, and emergency stops without needing the Flask dashboard open. Mobile-accessible monitoring. `yllvar/Kalshi-Quant-TeleBot` has a working implementation.

### M7. A/B Parameter Experiments
Run edge threshold variants in parallel with capped exposure. Auto-disable underperforming variants after N trades. Fills P5.3 gap in the priority checklist.

---

## Part 8 — Academic References

| Paper / Resource | Key Insight |
|-----------------|-------------|
| Gneiting et al. (2005), Monthly Weather Review | EMOS calibration: fit Gaussian to ensemble mean/spread to minimize CRPS |
| arXiv 2412.14144 | Kelly criterion for prediction markets: calibration errors more dangerous than sizing errors |
| UCI ML Repository dataset 514 | Free NWP temperature bias correction training data |
| Nature 2023 (Adaptive Bias Correction) | ML bias correction improves temperature skill 60–90% |
| PMC LightGBM paper | Station-level LightGBM cuts temperature RMSE ~30% |

---

## Part 9 — Prioritized Implementation Backlog

### Immediate (high impact, low effort)
1. **Fix NYC settlement station** — verify code uses KNYC coordinates, not KJFK
2. **Add NOAA MOS via IEM API** — free, drop-in data source, station-specific
3. **Per-city static bias correction** — simple offset table (Miami -3°F, NYC -1°F, Denver -2°F)
4. **METAR same-day lock-in** — add 2 PM+ local time METAR check before cron cycle

### Near-term (high impact, moderate effort)
5. **Add NBM (National Blend of Models)** — already blended by NWS, hourly updates
6. **Add ECMWF AIFS ensemble** — via ecmwf-opendata package
7. **Drawdown-tiered Kelly reduction** — tiers at -10% and -20% drawdown
8. **Per-market flash crash circuit breaker** — price-movement CB separate from data-source CB
9. **Confidence-tiered edge thresholds** — HIGH/MODERATE/LOW tiers

### Medium-term (high impact, higher effort)
10. **METAR settlement lag monitoring** — real-time post-5PM loop watching for settled outcomes
11. **Walk-forward backtesting** — fills P5 gap
12. **Per-city per-season Brier segmentation** — fills P10.1 drift detection gap
13. **Reliability diagram in dashboard** — calibration visualization
14. **Kalshi WebSocket integration** — real-time order book for microstructure signals
15. **Gaussian probability distribution method** — replace raw ensemble fraction counting

### Long-term
16. **ML-based bias correction** — LightGBM or simple sklearn model per city/season
17. **Cross-platform arbitrage scanner** — Kalshi ↔ Polymarket price gap monitoring
18. **A/B experiment framework** — fills P5.3 gap
19. **Strategy P&L attribution** — per-signal profit breakdown
20. **Telegram alerting**

---

## Sources

- [suislanchez/polymarket-kalshi-weather-bot](https://github.com/suislanchez/polymarket-kalshi-weather-bot)
- [OctagonAI/kalshi-deep-trading-bot](https://github.com/OctagonAI/kalshi-deep-trading-bot)
- [yllvar/Kalshi-Quant-TeleBot](https://github.com/yllvar/Kalshi-Quant-TeleBot)
- [braedonsaunders/homerun](https://github.com/braedonsaunders/homerun)
- [ImMike/polymarket-arbitrage](https://github.com/ImMike/polymarket-arbitrage)
- [evan-kolberg/prediction-market-backtesting](https://github.com/evan-kolberg/prediction-market-backtesting)
- [Weather Edge MCP / kalshiweatheredge.com](https://www.kalshiweatheredge.com/)
- [NOAA MDL MOS](https://vlab.noaa.gov/web/mdl/mos)
- [IEM MOS API](https://mesonet.agron.iastate.edu/mos/)
- [NOAA NBM on AWS](https://registry.opendata.aws/noaa-nbm/)
- [Aviation Weather Center METAR API](https://aviationweather.gov/api/data/metar)
- [ECMWF AIFS operational announcement](https://www.ecmwf.int/en/about/media-centre/news/2025/ecmwfs-ensemble-ai-forecasts-become-operational)
- [ecmwf-opendata PyPI](https://pypi.org/project/ecmwf-opendata/)
- [Herbie docs](https://herbie.readthedocs.io/)
- [Open-Meteo ECMWF API](https://open-meteo.com/en/docs/ecmwf-api)
- [minuteTemp.com](https://minutetemp.com/)
- [Kalshi WebSocket docs](https://docs.kalshi.com/getting_started/quick_start_websockets)
- [Kalshi API changelog](https://docs.kalshi.com/changelog)
- [arXiv 2412.14144](https://arxiv.org/abs/2412.14144)
- [UCI bias correction dataset](https://archive.ics.uci.edu/dataset/514/)
- [Nature adaptive bias correction](https://www.nature.com/articles/s41467-023-38874-y)
- [properscoring PyPI](https://pypi.org/project/properscoring/)
- [amiable.dev WebSocket deltas guide](https://amiable.dev/blog/arbiter-bot/2026-01-21-kalshi-websocket-deltas/)
