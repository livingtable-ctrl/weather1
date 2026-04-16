# Research Findings: External Systems & Improvement Ideas

**Last updated:** 2026-04-16 (expanded)  
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

#### HRRR (High-Resolution Rapid Refresh)
**Why:** 3km resolution vs GFS's 13km. Updated every hour (not 4x/day). Best short-range model for 0–18 hour forecasts — critical for same-day METAR lock-in strategy and morning cron runs. Free on NOMADS and AWS.

- **NOMADS:** `https://nomads.ncep.noaa.gov/pub/data/nccf/com/hrrr/prod/`
- **AWS Open Data:** `s3://noaa-hrrr-bdp-pds/`
- **Herbie:** `Herbie("2026-04-16 12:00", model="hrrr", product="sfc", fxx=6)`
- **Open-Meteo:** Available via Best Forecast API (blends HRRR with other models)
- **Key variable:** `TMP:2 m above ground` for surface temperature
- **When to use:** Hours 0–18 only; degrades significantly beyond 18 hours

#### RAP (Rapid Refresh)
**Why:** HRRR's parent model. 13km resolution, hourly updates, 0–21 hour window. Covers North America (HRRR is CONUS-only). Good backup when HRRR is unavailable.

- **NOMADS:** `https://nomads.ncep.noaa.gov/pub/data/nccf/com/rap/prod/`
- **AWS:** `s3://noaa-rap-pds/`
- **Herbie:** `Herbie("2026-04-16 12:00", model="rap", fxx=12)`

#### Historical ASOS Station Data (Bias Training)
**Why:** Years of actual observed station readings vs model forecasts. Essential for fitting per-city, per-season, per-lead-time bias correction models. Free via IEM.

- **IEM ASOS download:** `https://mesonet.agron.iastate.edu/request/download.phtml`
  - Select network (e.g., "NY_ASOS"), station (e.g., KNYC), date range, variables (tmpf = temp °F)
  - Returns CSV with hourly observations back to 1928 for some stations
- **Key columns:** `tmpf` (temp °F), `peak_wind_gust`, `p01i` (precip inches), `valid` (timestamp)
- **Use case:** Download 5+ years of KNYC daily highs, pair with archived MOS/GFS forecasts to train per-lead-time bias correction

#### CPC (Climate Prediction Center) Temperature Outlooks
**Why:** 6–14 day probabilistic outlooks for above/below/near-normal temperature. Useful signal for far-out markets (days 5+) where NWP skill is limited.

- **Free API:** `https://www.cpc.ncep.noaa.gov/products/predictions/`
- Updated Monday/Wednesday/Friday
- Provides tercile probabilities (above/near/below normal) by region

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

### Precipitation & Snowfall Market Settlement
**⚠️ Different settlement source than temperature.** Precipitation and snowfall markets do NOT use the same CLI report as temperature.

- **Precipitation:** Settles on NWS CLI for total daily precipitation — same CLI file but different field. Measured at the official ASOS station. Trace amounts (<0.005") may round to 0.00 — can matter for "any precipitation" markets
- **Snowfall:** Settles on NWS CLI snowfall field or CoCoRaHS crowdsourced network in some cases. More ambiguous than temperature — NWS may revise snowfall reports days later
- **"Any precipitation" markets:** Binary YES/NO on whether any precip was recorded. Very sensitive to trace amounts; models struggle here
- **Key asymmetry:** Model spread on precipitation events is much wider than temperature. Same edge threshold should NOT apply — requires higher confidence tier
- **Useful source:** NWS QPF (Quantitative Precipitation Forecast) `https://www.wpc.ncep.noaa.gov/qpf/`

### Kalshi API Downtime & Settlement Edge Cases
- Kalshi's settlement window is 6–9 AM ET next day. API can be slow during high-traffic settlement periods
- If a market's status shows `pending` instead of `finalized`, wait — do not treat as settled
- Kalshi has historically revised outcomes for sensor-error cases (rare but documented)
- Maintain local outcome cache with `>1 hour since close_time` guard (already in tracker.py `sync_outcomes`)

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

### S9. Order Book Flow Imbalance Signal
When YES ask volume is being absorbed rapidly (many trades hitting ask), informed traders may know something models don't. Treat sustained one-sided order flow as a confirming or contra-indicator.
- **Signal:** `(buy_volume - sell_volume) / total_volume` over last N trades via WebSocket `trade` channel
- **Use case:** If our model says 65% YES but flow is heavily selling YES, reduce confidence
- **Caution:** Thin markets make this noisy — require minimum volume threshold before using

### S10. Time-of-Day & Day-of-Week Patterns
Weather prediction market edges are not uniform across the day or week.
- **Morning (pre-9 AM ET):** New NWP runs haven't been priced in. Model-market divergence may be stale overnight
- **Afternoon (2–5 PM ET):** METAR readings accumulate; same-day markets approach resolution. Highest-confidence window for lock-in trades
- **Weekends:** Fewer professional forecasters watching. Market prices may lag model updates longer
- **Tracking:** Segment Brier score and realized edge by hour-of-day and day-of-week. Run for 2+ months before trading on it

### S11. Per-Forecast-Cycle Attribution
NWP models run at 00Z, 06Z, 12Z, 18Z. Performance varies by cycle due to data assimilation differences.
- **12Z GFS** generally considered most skillful for day-ahead forecasts (best satellite/radiosonde data)
- **00Z** can have cold bias in overnight initialization
- **Tracking:** Log `forecast_cycle` on every prediction (already done). After 50+ settled predictions per cycle, compare Brier scores. Apply cycle-specific multipliers to edge confidence

### S12. Precipitation Strategy — Dry/Wet Regime Separation
Precipitation markets require a completely different probability approach from temperature.
- **Model:** Use probability of precipitation (PoP) from NWS point forecast + ensemble agreement on precip occurrence (not just amount)
- **HRRR** is best short-range precip model; **GFS** degrades badly for convective events
- **Key signal:** If all ensemble members agree (100% or 0% PoP), edge is real. If models split 50/50, skip
- **Avoid:** "Any precip" markets during convective season (May–Sep) — thunderstorm timing uncertainty makes these very hard to price
- **Settlement source:** Verify CLI precip field vs QPF before trading

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

### R7. Risk-Adjusted Return Metrics (Sharpe / Sortino / Calmar)
Raw P&L and Brier score don't capture the quality of returns relative to risk taken.
- **Sharpe ratio:** `mean(daily_return) / std(daily_return) × sqrt(252)`. Target > 1.0
- **Sortino ratio:** Same but only penalizes downside deviation. Better for asymmetric return profiles like this bot
- **Calmar ratio:** `annualized_return / max_drawdown`. Shows return per unit of worst drawdown
- **Implementation:** Track daily P&L in paper ledger; compute rolling 30/90-day windows. Add to Flask dashboard
- **Benchmark:** Compare against "always bet YES at 50¢" or "random edge" baseline

### R8. Time-to-Expiry Risk Scaling
A 5-day-out market and a 6-hour-out market have fundamentally different risk profiles beyond what `time_decay_edge` currently captures.
- **Regime 1 (5+ days):** Climatology-heavy, wide uncertainty. Use full Kelly reduction. Cap at 50% of standard size
- **Regime 2 (2–4 days):** NWP-primary. Standard sizing applies
- **Regime 3 (<24 hours):** METAR/MOS-primary. Can justify up to 1.5× standard size if METAR confirms direction
- **Regime 4 (<4 hours):** Settlement imminent. Either very high confidence (METAR locked) or skip entirely — whipsaw risk from sensor corrections is high

### R9. Per-Trade Value at Risk (VaR)
Before each trade, estimate worst-case loss at 95th percentile.
- **Simple approach:** `VaR = bet_size × (1 - our_prob)` — max loss if wrong
- **Ensemble approach:** Use the spread of ensemble member probabilities as the uncertainty band. Wide spread = higher VaR
- **Portfolio VaR:** Sum correlated position VaR with `1 - correlation_discount`. Block trade if portfolio VaR > 5% of balance

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

### E5. Kalshi API Rate Limits
Production bots need to respect Kalshi's rate limits or risk being throttled/banned.
- **REST API:** ~10 requests/second sustained; burst to ~30/second briefly
- **Recommended pattern:** Batch market fetches — use `GET /markets?series_ticker=KXHIGH` (returns all cities at once) instead of one call per market
- **WebSocket:** Preferred for real-time data; single persistent connection vs repeated REST polling
- **Backoff strategy:** Current `Retry(total=3, backoff_factor=1.0)` is correct. Add jitter for concurrent bot instances
- **Monitor:** Log all API call latencies and HTTP 429 responses. Alert if 429s exceed 5% of calls in a cycle

### E6. Order Splitting for Large Positions
Kelly can suggest a large position when edge + confidence are both high. Entering a single large order in a thin market moves the price against you.
- **Rule:** If bet size > 10% of market's open interest, split into 3–5 child orders placed 30–60 seconds apart
- **Price check:** After each partial fill, re-evaluate mid-price before placing next chunk
- **Implementation:** New `_place_order_split(ticker, side, total_qty, chunks=3)` helper in paper.py

### E7. GTC Order Lifecycle Management
Good-Till-Cancelled limit orders accumulate silently if not managed.
- **Problem:** A limit order placed at yesterday's mid-price may fill at a stale price after a model update shifts our probability
- **Rule:** Cancel all open GTC orders older than 1 NWP cycle (6 hours) and reassess
- **Implementation:** At cron startup, call `GET /portfolio/orders?status=open`, cancel any order where `(now - created_time) > 6h` and the current edge no longer justifies entry
- **Track:** Log GTC fill rate (filled vs cancelled) as an execution quality metric

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

### M8. Risk-Adjusted Return Dashboard Metrics
Add to Flask dashboard alongside existing Brier/balance charts:
- **Sharpe ratio** (rolling 30-day and all-time)
- **Sortino ratio** (rolling 30-day)
- **Max drawdown** (peak-to-trough, with recovery date)
- **Calmar ratio** (annualized return / max drawdown)
- **Win rate vs. edge-weighted expected win rate** — are we winning as often as our edge predicts?

### M9. Lead-Time Skill Decay Per City
Currently `get_edge_decay_curve()` pools all cities. Per-city curves reveal which cities have reliable edges at which horizons.
- **Format:** `{city: [{days_out: 1, avg_edge: 0.12, brier: 0.14}, {days_out: 3, ...}, ...]}`
- **Use case:** If NYC edge disappears beyond day 2 but Dallas holds to day 4, apply city-specific `MAX_DAYS_OUT` caps
- **Threshold:** Retire city-horizon combination if avg_edge < 1% over 30+ samples

### M10. Ensemble Spread vs. Realized Error Calibration
Is our ensemble spread actually predictive of forecast uncertainty?
- **Spread-error correlation:** `corr(ensemble_std, abs(ensemble_mean - actual))`. Should be > 0.4 to be useful
- **Spread-error diagram:** Plot `ensemble_std` bins vs mean absolute error. Perfect calibration = diagonal line
- **Underdispersion warning:** If spread consistently underestimates error, apply a spread inflation factor. GFS is typically underdispersed
- **Track:** Log `ensemble_std` alongside `ensemble_mean` in predictions DB. Compute correlation weekly

### M11. Live Trading Graduation Criteria
Before switching from paper to live trading, require all of the following:
| Criterion | Minimum Threshold |
|-----------|------------------|
| Settled paper trades | ≥ 50 |
| Brier score | < 0.20 |
| Brier Skill Score vs market | > 0.05 |
| 30-day Sharpe ratio | > 0.8 |
| Max drawdown | < 15% of starting balance |
| Win rate (settled) | > 45% |
| Consecutive loss record | Never > 7 in a row |
| P&L positive | Yes, after simulated fees |

Graduate incrementally: start with 10% of planned live bankroll, run paper + live in parallel for 2 weeks, then scale up.

---

## Part 8 — Statistical Calibration Methods

### EMOS (Ensemble Model Output Statistics)
The standard post-processing method for ensemble weather forecasts. Fits a Gaussian to ensemble output using CRPS minimization.

**How it works:**
- Fit parameters `(a, b, c, d)` such that: `forecast = Normal(μ, σ)` where `μ = a + b × ensemble_mean` and `σ² = c + d × ensemble_variance`
- Parameters trained per-station, per-season, per-lead-time on historical data
- Corrects both mean bias AND spread bias simultaneously

**Why better than current approach:**
- Current `normal_dist` method uses raw NWP sigma without calibrating it against historical station errors
- EMOS-calibrated sigma is typically 20–40% more accurate than raw ensemble spread

**Implementation:**
```python
# pip install properscoring
from properscoring import crps_gaussian
# Minimize: sum(crps_gaussian(obs, mu, sigma)) over training window
```

**Reference:** Gneiting et al. (2005), *Monthly Weather Review* — the foundational paper

---

### BMA (Bayesian Model Averaging)
Weights multiple model forecasts by their historical skill to produce a calibrated mixture distribution.

**How it works:**
- Each model `k` gets weight `w_k` proportional to likelihood of observed outcomes given model forecasts
- Final forecast: weighted mixture of Gaussian distributions, one per model
- Weights updated via EM algorithm on rolling training window (30–60 days)

**Why useful here:**
- Current system blends models with fixed or MAE-based weights. BMA produces proper probabilistic weights with uncertainty quantification
- Automatically down-weights a model that's been performing poorly recently

**Implementation:** `pip install pybma` or implement EM directly (15–20 lines)

---

### Isotonic Regression Calibration
Non-parametric, post-hoc calibration. Learns a monotone mapping from raw model probabilities to calibrated probabilities.

**How it works:**
```python
from sklearn.isotonic import IsotonicRegression
ir = IsotonicRegression(out_of_bounds="clip")
ir.fit(raw_probs_train, outcomes_train)
calibrated = ir.predict(raw_probs_test)
```
**Advantage over Platt scaling:** Makes no Gaussian assumption. Works well with Brier-trained models.
**Requirement:** Needs 100+ samples per city-season-condition slice to be reliable.

---

### Proper Scoring Rules Beyond Brier
| Score | Formula | Key Property |
|-------|---------|-------------|
| Brier | `(p - y)²` | Quadratic; penalizes overconfidence moderately |
| Log score | `-y log(p) - (1-y) log(1-p)` | Infinite penalty for confident wrong predictions; strictly proper |
| Spherical | `(py + (1-p)(1-y)) / sqrt(p² + (1-p)²)` | Bounded; robust to outliers |
| CRPS | Generalizes Brier to continuous distributions | Best for evaluating temperature CDFs, not binary outcomes |

**Recommendation:** Track both Brier (current) and log score. Log score catches dangerous overconfidence (e.g., predicting 95% when true probability is 50%) that Brier lets slide.

---

## Part 9 — Academic References

| Paper / Resource | Key Insight |
|-----------------|-------------|
| Gneiting et al. (2005), Monthly Weather Review | EMOS calibration: fit Gaussian to ensemble mean/spread to minimize CRPS |
| Gneiting & Raftery (2007), JASA | Strictly proper scoring rules — full taxonomy of Brier, log, CRPS, spherical |
| Raftery et al. (2005), Monthly Weather Review | BMA for ensemble forecasts — the original BMA weather paper |
| arXiv 2412.14144 | Kelly criterion for prediction markets: calibration errors more dangerous than sizing errors |
| UCI ML Repository dataset 514 | Free NWP temperature bias correction training data |
| Nature 2023 (Adaptive Bias Correction) | ML bias correction improves temperature skill 60–90% |
| PMC LightGBM paper | Station-level LightGBM cuts temperature RMSE ~30% |
| Hamill & Colucci (1997), Monthly Weather Review | Spread-skill relationship for ensemble forecasts — foundational underdispersion paper |
| Toth & Kalnay (1993), BAMS | Ensemble forecasting origins — why ensemble spread estimates forecast uncertainty |

---

## Part 10 — Operational Considerations

### Kalshi Fees & Break-Even Analysis
Understanding the fee structure is critical to knowing the minimum edge required to be profitable.

| Order Type | Fee on Win | Fee on Loss |
|------------|-----------|------------|
| Taker (market order) | 7% of winnings | 0% |
| Maker (limit at mid) | ~0–3% (varies) | 0% |

**Break-even edge calculation:**
- At 7% taker fee: if YES costs $0.60 and wins $1.00 → net win = $0.40 × (1 - 0.07) = $0.372. Break-even = our_prob > 0.60 / (0.60 + 0.372) = 61.7% vs market's 60%. Need ~2% edge just to cover fees
- **Implication:** PAPER_MIN_EDGE=5% is correct minimum for paper. For live with taker fees, effective minimum should be ~7–8%
- **Maker advantage:** Posting limit orders at mid reduces fees significantly. At thin edges (5–7%), maker vs taker is the difference between profit and loss

### Infrastructure & Latency
- **Windows Task Scheduler reliability:** Adequate for 4x/day NWP cycles but has known issues with sleep/wake. For sub-hourly cycles or METAR monitoring, consider migrating to a cloud VM (e.g., AWS t3.micro ~$8/month, always-on)
- **Network latency to Kalshi:** Kalshi servers are in AWS us-east-1 (Virginia). A VPS in the same region gets ~2ms API latency vs 50–200ms from residential ISP
- **For METAR lock-in strategy:** Sub-second latency matters if competing with other bots watching the same METAR update. US East VPS recommended
- **Storage:** SQLite is fine up to ~500k rows. For 2+ years of 4x/day runs across 10 cities, expect ~100k predictions/year — well within SQLite range

### Tax Treatment (US)
- Kalshi contracts are currently treated as **Section 1256 contracts** (60% long-term / 40% short-term capital gains) for US taxpayers — more favorable than ordinary income
- This classification is not 100% settled; consult a tax professional before trading significant sums
- **Record-keeping:** The existing paper + execution logs provide adequate audit trail. Export to CSV annually via `py main.py export`
- **Wash sale rules:** Do not apply to prediction market contracts under current IRS guidance

### Bot Monitoring Without the Dashboard
For remote monitoring without Flask running:
- `py main.py brief` — morning summary to stdout or email
- Pipe cron.log to a webhook (Slack, Discord, ntfy.sh) for real-time alerts without Telegram integration
- `ntfy.sh` is free, no account required: `curl -d "Trade placed: KXHIGHNYC +$12" ntfy.sh/your-topic`
- Health check: `py main.py shadow` confirms model is seeing markets even if not trading

---

## Part 11 — Prioritized Implementation Backlog

### Immediate (high impact, low effort)
1. **Fix NYC settlement station** — verify code uses KNYC coordinates, not KJFK
2. **Add NOAA MOS via IEM API** — free, drop-in data source, station-specific
3. **Per-city static bias correction** — simple offset table (Miami -3°F, NYC -1°F, Denver -2°F)
4. **METAR same-day lock-in** — add 2 PM+ local time METAR check before cron cycle
5. **Add HRRR via Herbie** — hourly high-res model for same-day and next-day trades
6. **Live trading fee correction** — raise effective live min edge to ~8% to account for 7% taker fee

### Near-term (high impact, moderate effort)
7. **Add NBM (National Blend of Models)** — already blended by NWS, hourly updates
8. **Add ECMWF AIFS ensemble** — via ecmwf-opendata package
9. **Drawdown-tiered Kelly reduction** — tiers at -10% and -20% drawdown (R2)
10. **Per-market flash crash circuit breaker** — price-movement CB separate from data-source CB (R3)
11. **Confidence-tiered edge thresholds** — HIGH/MODERATE/LOW tiers (S3)
12. **Time-to-expiry risk regime scaling** — 4 regimes from 5+ days to <4 hours (R8)
13. **GTC order lifecycle management** — cancel stale open orders at cron startup (E7)
14. **Per-forecast-cycle attribution** — segment Brier by 00Z/06Z/12Z/18Z (S11)

### Medium-term (high impact, higher effort)
15. **METAR settlement lag monitoring** — real-time post-5PM loop watching for settled outcomes (S5)
16. **Walk-forward backtesting** — proper train/test rolling window
17. **Per-city per-season lead-time decay curves** — city-specific MAX_DAYS_OUT (M9)
18. **Reliability diagram in dashboard** — calibration visualization (M1)
19. **Kalshi WebSocket integration** — real-time order book + flow imbalance signal (E1, S9)
20. **EMOS calibration** — replace raw sigma with CRPS-minimized Gaussian fit (Part 8)
21. **Sharpe/Sortino/Calmar on dashboard** — risk-adjusted return metrics (M8)
22. **Log score tracking** — complement to Brier for detecting dangerous overconfidence

### Long-term
23. **ML-based bias correction** — LightGBM or sklearn model per city/season
24. **BMA ensemble weighting** — EM-based probabilistic model weights
25. **Cross-platform arbitrage scanner** — Kalshi ↔ Polymarket price gap monitoring (S7)
26. **Strategy P&L attribution** — per-signal profit breakdown (M5)
27. **Telegram / ntfy.sh alerting** — mobile-accessible monitoring (M6)
28. **Spread inflation correction** — fix GFS underdispersion for better sigma estimates (M10)
29. **Precipitation strategy module** — separate pipeline for precip/snowfall markets (S12)
30. **Historical ASOS bias training** — download IEM data, fit per-city regression models (S2)

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
- [NOAA HRRR on AWS](https://registry.opendata.aws/noaa-hrrr-pds/)
- [NOAA RAP on AWS](https://registry.opendata.aws/noaa-rap-pds/)
- [IEM ASOS Historical Data](https://mesonet.agron.iastate.edu/request/download.phtml)
- [NOAA CPC Temperature Outlooks](https://www.cpc.ncep.noaa.gov/products/predictions/)
- [NOAA QPF (Quantitative Precipitation Forecast)](https://www.wpc.ncep.noaa.gov/qpf/)
- [Gneiting & Raftery (2007), JASA — Strictly Proper Scoring Rules](https://www.tandfonline.com/doi/abs/10.1198/016214506000001437)
- [Raftery et al. (2005) — BMA for ensemble forecasts](https://journals.ametsoc.org/view/journals/mwre/133/5/mwr2906.1.xml)
- [Hamill & Colucci (1997) — Spread-skill relationship](https://journals.ametsoc.org/view/journals/mwre/125/7/1520-0493_1997_125_1731_vetpef_2.0.co_2.xml)
- [ntfy.sh — free push notification service](https://ntfy.sh/)
