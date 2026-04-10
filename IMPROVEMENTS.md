## COMPREHENSIVE IMPROVEMENT LIST — KALSHI WEATHER PREDICTION MARKET BOT

Based on my thorough read-through of all core Python files, I've identified every possible improvement organized by category. This is an exhaustive list.

**Status key:** ✅ Done  ⬜ Not yet done

---

### **ERROR HANDLING & ROBUSTNESS**

1. ✅ **Bare `except Exception` clauses (125 instances)**
   - **Files**: weather_markets.py, paper.py, tracker.py, backtest.py, nws.py, web_app.py, alerts.py, main.py
   - **Issue**: Silent failures; no distinction between network errors, data corruption, API changes, and bugs
   - **Impact**: Makes debugging production issues nearly impossible
   - **Difficulty**: Medium
   - **Solution**: Replace with specific exception types (requests.ConnectionError, requests.Timeout, ValueError, KeyError, etc.)

2. ✅ **No retry logic for API calls beyond basic backoff**
   - **Files**: nws.py, climatology.py, weather_markets.py
   - **Issue**: Single transient failures (network hiccup) kill entire market analysis
   - **Difficulty**: Medium
   - **Solution**: Implement exponential backoff with jitter; separate retryable from non-retryable errors

3. ⬜ **No circuit breaker pattern for failing data sources**
   - **Files**: nws.py, climatology.py
   - **Issue**: If NWS API is down, system keeps hammering it for hours
   - **Difficulty**: Medium
   - **Solution**: Track source failure rates; switch to degraded mode or skip source temporarily

4. ✅ **Stale forecast cache returned when API fails (climatology.py:76-79)**
   - **Issue**: If API is down and cache >1 year old, model returns stale 2024 data for 2026 forecast
   - **Difficulty**: Easy
   - **Solution**: Return None + log warning; let caller handle gracefully

5. ✅ **No exception type in `log_order_result` error parameter**
   - **Files**: execution_log.py
   - **Issue**: Stores unstructured error strings; hard to aggregate failure types
   - **Difficulty**: Easy
   - **Solution**: Store structured error info (type, code, message)

6. ✅ **API rate-limit handling incomplete**
   - **Files**: backtest.py, weather_markets.py
   - **Issue**: Retries on 429 but may not respect Retry-After header
   - **Difficulty**: Easy
   - **Solution**: Parse Retry-After; implement smarter backoff

7. ✅ **No timeout enforcement on slow endpoints**
   - **Files**: nws.py, climatology.py, weather_markets.py
   - **Issue**: Some requests have 60s timeout; others 15s; inconsistent
   - **Difficulty**: Easy
   - **Solution**: Centralize timeout constants; apply consistently

8. ⬜ **Silent failure if disk write fails (atomic writes catch but don't retry)**
   - **Files**: paper.py, alerts.py, execution_log.py, tracker.py
   - **Issue**: If disk full, data is lost silently
   - **Difficulty**: Medium
   - **Solution**: Attempt backoff + fallback location; raise informative exception

---

### **DATA INTEGRITY & CORRECTNESS**

9. ✅ **Bias correction weights recent predictions exponentially but doesn't validate if "recent" is actually old**
   - **Files**: tracker.py:169-216
   - **Issue**: If no new trades for 30+ days, old bias is weighted heavily — creates false confidence
   - **Difficulty**: Easy
   - **Solution**: Return None or low-confidence bias if no trades in last 14 days

10. ⬜ **`get_bias()` doesn't account for market condition type**
    - **Issue**: NYC HIGH > 70 may have different bias than NYC HIGH > 85; function conflates all types
    - **Difficulty**: Medium
    - **Solution**: Add condition_type parameter; filter by it

11. ⬜ **Brier score calculation doesn't normalize for base rate**
    - **Issue**: If a market is 90% likely to settle YES, naive model predicting 0.9 gets good Brier, but it's not skill
    - **Difficulty**: Hard
    - **Solution**: Compute Brier for model vs climatology baseline; report relative improvement

12. ⬜ **Confusion matrix threshold hardcoded to 0.5 (tracker.py:648)**
    - **Issue**: Model might be calibrated to predict at 0.4 or 0.6; threshold should be optimized
    - **Difficulty**: Medium
    - **Solution**: Add threshold parameter; compute optimal threshold from historical data

13. ⬜ **Market calibration buckets have hardcoded 10% widths**
    - **Issue**: If most predictions are 0.45–0.55, buckets are too coarse
    - **Difficulty**: Easy
    - **Solution**: Adaptive bucketing based on prediction distribution

14. ⬜ **Edge decay curve doesn't account for market type**
    - **Issue**: Temperature above/below markets might have different decay than precip; conflated together
    - **Difficulty**: Medium
    - **Solution**: Segment decay curve by condition type

15. ⬜ **Paper trading PnL calculation doesn't account for fills at different times within day**
    - **Files**: paper.py
    - **Issue**: Assumes entry price is entry_price, but real fills might slip; backtest is unrealistic
    - **Difficulty**: Medium
    - **Solution**: Allow variable entry_price per contract; aggregate realistic slippage

16. ✅ **No validation that market settlement data is final**
    - **Files**: tracker.py:509-517
    - **Issue**: Outcome recorded as soon as market has a result, but Kalshi may revise results post-settlement
    - **Difficulty**: Medium
    - **Solution**: Only accept outcomes if status is "finalized" AND age > 1 hour

17. ✅ **Logged outcomes not deduplicated properly**
    - **Files**: tracker.py:159
    - **Issue**: `INSERT OR REPLACE` overwrites prior outcome if ticker was logged multiple times
    - **Difficulty**: Easy
    - **Solution**: Check for existing outcome; refuse duplicate settlement

18. ⬜ **Ensemble member MAE is averaged globally, not stratified**
    - **Files**: tracker.py:541-577
    - **Issue**: If GFS is good in winter but bad in summer, global MAE is misleading
    - **Difficulty**: Medium
    - **Solution**: Add seasonal + region breakdown to member_accuracy

19. ✅ **ROC AUC computation doesn't handle edge case where all predictions are identical**
    - **Files**: tracker.py:730-731
    - **Issue**: Returns None; should handle this gracefully
    - **Difficulty**: Easy
    - **Solution**: Return {auc: 0.5, note: "no variance in predictions"}

20. ✅ **Walk-forward windows can overlap or have gaps**
    - **Files**: backtest.py:459-474
    - **Issue**: If window_size=60 and step_size=30, windows overlap; if step_size=70, gaps exist
    - **Difficulty**: Easy
    - **Solution**: Ensure step_size fits exactly into days_total; document expected behavior

21. ⬜ **Holdout fraction applied per-result but not stratified by city or condition**
    - **Files**: backtest.py:199-206
    - **Issue**: Holdout set might be all NYC > 70; doesn't test generalization to other conditions
    - **Difficulty**: Medium
    - **Solution**: Stratified holdout: ensure holdout has representative mix of cities, condition types

22. ✅ **Archive ensemble temps seeded with fixed random seed (42)**
    - **Files**: backtest.py:102
    - **Issue**: Every backtest run returns identical "member" temps; no true stochasticity
    - **Difficulty**: Easy
    - **Solution**: Seed with date or ticker hash to get variety across backtests

23. ⬜ **Forecast probability doesn't account for ensemble censoring**
    - **Files**: weather_markets.py:~400
    - **Issue**: If ensemble is truncated (e.g., we throw out >99th percentile), probability is biased
    - **Difficulty**: Hard
    - **Solution**: Track which members were excluded; recompute probability over full support

24. ✅ **Time-risk factor isn't validated against actual market behavior**
    - **Files**: weather_markets.py:648-679
    - **Issue**: Assumes close_time_str is always present and parseable; no fallback
    - **Difficulty**: Easy
    - **Solution**: Return (None, 1.0) if parse fails; don't crash

---

### **MODEL & FORECASTING ISSUES**

25. ⬜ **Ensemble weighting doesn't account for recent forecast accuracy**
    - **Files**: weather_markets.py:311-351
    - **Issue**: Static seasonal weights; if GFS is 2°F colder than reality recently, still uses full weight
    - **Difficulty**: Hard
    - **Solution**: Load recent accuracy from tracker; weight models by recent MAE

26. ⬜ **No reforecasting for persistence / baseline model**
    - **Files**: climatology.py, weather_markets.py
    - **Issue**: Model doesn't include "forecast tomorrow's temp = today's temp" baseline; missing a strong competitor
    - **Difficulty**: Medium
    - **Solution**: Add persistence forecast; blend it in at 0-20% weight

27. ✅ **Climatological window is static (±21 days) regardless of season**
    - **Files**: climatology.py:21-24, 100-103
    - **Issue**: ±21 day window in shoulder months is too wide (smears transitions); shoulder window (±14) is arbitrary
    - **Difficulty**: Easy
    - **Solution**: Make window configurable per city; auto-tune based on local climate noise

28. ⬜ **ENSO and climate indices loaded but not used in forecast**
    - **Files**: climate_indices.py exists but imported nowhere
    - **Issue**: Dead code; model ignores teleconnections
    - **Difficulty**: Medium
    - **Solution**: Integrate ENSO index into ensemble weighting; boost winter forecast in El Niño years

29. ⬜ **Feels-like temperature formula hardcoded for two regimes**
    - **Files**: weather_markets.py:282-310
    - **Issue**: Doesn't handle moist-cold (wind chill + high humidity) properly
    - **Difficulty**: Easy
    - **Solution**: Add intermediate regime; validate coefficients against NOAA

30. ✅ **Normal CDF approximation may have numerical issues at tails**
    - **Files**: utils.py:28-30
    - **Issue**: `erfc()` can underflow for x >> μ+5σ; returns 0 when probability is just very small
    - **Difficulty**: Easy
    - **Solution**: Use `scipy.stats.norm` if available; fall back to logcdf to avoid underflow

31. ⬜ **No weighting by forecast model confidence**
    - **Files**: weather_markets.py
    - **Issue**: Blends GFS and ECMWF with equal weight even if ECMWF has much wider ensemble spread
    - **Difficulty**: Hard
    - **Solution**: Weight by inverse ensemble variance; high confidence gets higher weight

32. ✅ **Regime detection assumes Gaussian, doesn't adapt for non-normal distributions**
    - **Files**: regime.py
    - **Issue**: If temperature forecast is bimodal (e.g., 50% cold, 50% warm), boost is nonsensical
    - **Difficulty**: Hard
    - **Solution**: Detect multimodality; return "bimodal" regime; lower confidence boost

33. ⬜ **NWS forecast ignored if ensemble data available**
    - **Files**: weather_markets.py:~1300
    - **Issue**: NWS is calibrated and often better for 1-5 days; should be blended, not replaced
    - **Difficulty**: Medium
    - **Solution**: Use NWS as 0.3-0.5 weight in ensemble blend

34. ⬜ **Snow accumulation forecast uses precipitation threshold naively**
    - **Files**: weather_markets.py:~1094-1182
    - **Issue**: Doesn't model snow-to-liquid conversion; assumes 10:1 ratio everywhere (wrong in wet/dry climates)
    - **Difficulty**: Hard
    - **Solution**: Estimate wet-bulb temperature; use climate-specific ratios

35. ✅ **Precip ensemble fetch doesn't validate if data is for target date**
    - **Files**: weather_markets.py:908-956
    - **Issue**: May return empty list without indicating why; caller doesn't know if date is unsupported
    - **Difficulty**: Easy
    - **Solution**: Return (list, bool) where bool indicates "date is in forecast range"

36. ✅ **Bootstrap CI ignores correlation between temperature and precipitation**
    - **Files**: weather_markets.py:844-868
    - **Issue**: Resamples as if independent; real distribution might have precip suppress temperature
    - **Difficulty**: Hard
    - **Solution**: Use copula-based resampling; sample pairs preserving correlation

37. ⬜ **Model doesn't detect forecast errors due to forecast cycles**
    - **Issue**: Forecasts issued at 6z may be better/worse than 12z; not tracked
    - **Difficulty**: Medium
    - **Solution**: Log forecast cycle (6z/12z/18z/00z); compute skill by cycle

38. ✅ **Consistency checker only validates above/below monotonicity, not between**
    - **Files**: consistency.py:90-145
    - **Issue**: Doesn't check P(60-65) + P(65-70) ≈ P(60-70); missing intra-range arbitrage
    - **Difficulty**: Medium
    - **Solution**: Add between-range consistency checks

---

### **TRADING & POSITION MANAGEMENT**

39. ⬜ **Kelly fraction computed without accounting for trade edge uncertainty**
    - **Files**: weather_markets.py:888-906
    - **Issue**: Kelly is f* = (p*odds - 1) / odds; uses point estimate of p, not full distribution
    - **Difficulty**: Hard
    - **Solution**: Use Bayesian Kelly; integrate over posterior of edge

40. ✅ **Exit targets don't account for commission on exit**
    - **Files**: paper.py:163-221
    - **Issue**: If exit_target=0.99 and user bought at 0.50, net payout after 7% fee is not 0.99
    - **Difficulty**: Easy
    - **Solution**: Adjust exit target down by 7% fee; document in docstring

41. ✅ **Drawdown scaling factor has discontinuities**
    - **Files**: paper.py:101-126
    - **Issue**: At 60% recovery, scaling jumps from 0.25 to 0.30; creates cliff behaviors
    - **Difficulty**: Easy
    - **Solution**: Use smooth interpolation (e.g., cubic spline) instead of tiers

42. ✅ **No minimum position size enforced; can place trades costing $0.01**
    - **Files**: paper.py:147-161
    - **Issue**: Doesn't match real Kalshi minimum (typically 1 contract @ $0.01 = $0.01 cost)
    - **Difficulty**: Easy
    - **Solution**: Enforce min_cost = 0.05; reject smaller orders

43. ✅ **Correlated exposure cap uses hardcoded city pairs**
    - **Files**: paper.py:44-48, monte_carlo.py:12-17
    - **Issue**: NYC/Boston corr = 0.7 is empirically tested for 2023; may change; hardcoded
    - **Difficulty**: Medium
    - **Solution**: Load correlations from backtest; auto-update yearly

44. ✅ **No position sizing based on position age**
    - **Files**: paper.py
    - **Issue**: A 7-day-old position takes same Kelly allocation as a fresh trade; should age out
    - **Difficulty**: Easy
    - **Solution**: Scale Kelly by (1 - age_days/MAX_POSITION_AGE_DAYS); fully paused at MAX_POSITION_AGE_DAYS

45. ✅ **Streak-based position scaling only checks consecutive losses, not variance**
    - **Files**: paper.py:563-593
    - **Issue**: 3 losses of $0.01 each pauses trading; 3 losses of $100 each also pauses trading (unfair)
    - **Difficulty**: Medium
    - **Solution**: Scale pause by streak PnL, not just count

46. ✅ **Daily loss limit doesn't account for open position mark-to-market**
    - **Files**: paper.py:599-612
    - **Issue**: Checks settled PnL only; ignores that open position might be underwater
    - **Difficulty**: Medium
    - **Solution**: Compute daily PnL as settled + MTM of open positions

47. ✅ **No maximum position concentration on a single ticker**
    - **Issue**: Can place 10 contracts of the same market; concentrated risk
    - **Difficulty**: Easy
    - **Solution**: Add MAX_SINGLE_TICKER_EXPOSURE cap

48. ✅ **Monte Carlo simulation doesn't validate trade win probabilities**
    - **Files**: monte_carlo.py:20-166
    - **Issue**: Uses entry_prob without confirming it's plausible (could be 0.99 or 0.01 from stale data)
    - **Difficulty**: Easy
    - **Solution**: Clip to [0.1, 0.9] range with warning if adjusted

49. ⬜ **Correlation matrix is hardcoded; doesn't update from recent backtest results**
    - **Files**: monte_carlo.py:12-17
    - **Issue**: Uses static correlations; if market structure changes, simulation is wrong
    - **Difficulty**: Medium
    - **Solution**: Load from backtest walk-forward results; re-estimate yearly

50. ⬜ **No slippage modeling for large orders**
    - **Files**: paper.py:403-422
    - **Issue**: Assumes can fill 100-contract order at mid-price; real markets have depth issues
    - **Difficulty**: Medium
    - **Solution**: Add slippage_kelly_scale that increases with quantity; model market depth

51. ⬜ **Portfolio Kelly doesn't account for hedge ratios**
    - **Files**: paper.py:352-401
    - **Issue**: If short 5 NYC and long 10 Chicago, treats as correlated but doesn't compute hedge
    - **Difficulty**: Hard
    - **Solution**: Build covariance matrix from open positions; compute efficient portfolio

52. ✅ **Graduation check is too lenient**
    - **Files**: paper.py:635-660
    - **Issue**: 60% win rate on 10 trades is likely noise; should require min 30+ trades or tighter threshold
    - **Difficulty**: Easy
    - **Solution**: Adjust min_trades to 30; increase threshold to 0.55+ (accounting for fees)

---

### **CALIBRATION & BIAS CORRECTION**

53. ✅ **Bias correction applied at analysis time but not re-applied after settlement**
    - **Files**: weather_markets.py:analyze_trade, tracker.py:log_prediction
    - **Issue**: Forecast prob is adjusted for known bias, but original is stored; hard to audit
    - **Difficulty**: Easy
    - **Solution**: Store both raw and bias-corrected probabilities

54. ⬜ **Monthly bias assumes calendar month boundary, not market settlement month**
    - **Files**: tracker.py:169-190
    - **Issue**: Market settling in late March is assigned to March, but forecast is for early-season April conditions
    - **Difficulty**: Hard
    - **Solution**: Assign to target_date's month, not prediction date

55. ⬜ **Bias correction doesn't account for edge selectivity**
    - **Issue**: We only trade high-edge markets; we select on a variable (our forecast prob), creating selection bias
    - **Difficulty**: Hard
    - **Solution**: Measure bias on all markets, not just traded ones; separate skill from selection bias

56. ⬜ **Per-city calibration doesn't account for different condition types**
    - **Files**: tracker.py:362-389
    - **Issue**: NYC might be well-calibrated on temperature but biased on precip; conflated
    - **Difficulty**: Medium
    - **Solution**: Add condition_type breakdown to get_calibration_by_city

57. ⬜ **Confidence intervals don't shrink as you get more data**
    - **Issue**: CI width is from bootstrap; doesn't improve as N → ∞
    - **Difficulty**: Medium
    - **Solution**: Add Bayesian posterior interval that shrinks with more observations

58. ✅ **No automated bias correction mechanism**
    - **Issue**: Bias is computed but not used in real-time forecasting
    - **Difficulty**: Medium
    - **Solution**: Apply bias adjustment in analyze_trade automatically

59. ✅ **Calibration metrics computed globally but markets differ by season**
    - **Issue**: Brier in summer vs winter is very different; should be tracked separately
    - **Difficulty**: Easy
    - **Solution**: Add seasonal breakdown to all calibration functions

60. ⬜ **ROC curve computed with fixed threshold; doesn't show threshold optimization curve**
    - **Issue**: User can't see what threshold maximizes F1 or other metrics
    - **Difficulty**: Medium
    - **Solution**: Return ROC + optimal thresholds for F1, Precision-Recall tradeoff

---

### **PRICING & EDGE DETECTION**

61. ✅ **Edge calculation doesn't account for bid-ask spread**
    - **Files**: weather_markets.py:parse_market_price, consistency.py
    - **Issue**: If market is bid 0.40, ask 0.42, and we want to buy, real entry is 0.42, not mid 0.41
    - **Difficulty**: Easy
    - **Solution**: Compute edge using entry-side price, not mid-price

62. ✅ **No detection of wide spreads (illiquid markets)**
    - **Files**: weather_markets.py:788-800
    - **Issue**: If spread is >5%, edge is likely evaporated by slippage; should warn
    - **Difficulty**: Easy
    - **Solution**: Flag markets with spread >5% as "illiquid"; reduce Kelly by spread/4

63. ⬜ **Time decay of edge not modeled**
    - **Issue**: Edge relative to market close should be larger if we trade now vs day before close
    - **Difficulty**: Hard
    - **Solution**: Adjust edge linearly to zero at close_time

64. ✅ **No detection of hedging opportunities**
    - **Files**: weather_markets.py:1503-1520
    - **Issue**: Function exists but is unused; never called in analysis pipeline
    - **Difficulty**: Easy
    - **Solution**: Call detect_hedge_opportunity in main analyze loop; suggest hedge trades

65. ⬜ **Price improvement tracking not implemented**
    - **Issue**: No record of whether limit orders filled at better prices; can't measure execution quality
    - **Difficulty**: Medium
    - **Solution**: Log desired entry price vs actual fill price; report statistics

---

### **API & DATA FETCHING**

66. ✅ **No caching for Kalshi market listings**
    - **Files**: weather_markets.py:507-563
    - **Issue**: Calls get_markets(limit=200) on every analyze; hammers API
    - **Difficulty**: Easy
    - **Solution**: Cache for 60 seconds; allow force-refresh if needed

67. ⬜ **Kalshi client has manual retry loop instead of using a robust library**
    - **Files**: kalshi_client.py
    - **Issue**: Implements own exponential backoff; error-prone and duplicated in backtest.py
    - **Difficulty**: Medium
    - **Solution**: Use `requests.adapters.HTTPAdapter` with Retry strategy

68. ✅ **User-Agent header is hardcoded and might get requests blocked**
    - **Files**: nws.py:18
    - **Issue**: If contact@example.com is rate-limited, can't fix without code change
    - **Difficulty**: Easy
    - **Solution**: Load from environment variable; default to user@localhost or similar

69. ⬜ **No request logging for audit trail**
    - **Issue**: Can't debug "why did we skip market X"; no record of API calls
    - **Difficulty**: Medium
    - **Solution**: Log all API requests to predictions.db; include timestamp, endpoint, response code

70. ✅ **Ensemble member count can be zero without error**
    - **Files**: weather_markets.py:_fetch_model_ensemble
    - **Issue**: Returns [] if date not in forecast; caller may assume N > 0
    - **Difficulty**: Easy
    - **Solution**: Return None if N=0; caller must check

71. ✅ **No validation of Open-Meteo API response structure**
    - **Issue**: If API returns unexpected JSON, code crashes or returns garbage
    - **Difficulty**: Easy
    - **Solution**: Add schema validation; use TypedDict for responses

72. ✅ **Archive precip fetch returns float | None inconsistently**
    - **Files**: backtest.py:118
    - **Issue**: Sometimes [] (no temps), sometimes None (API error); caller must handle both
    - **Difficulty**: Easy
    - **Solution**: Return (float | None, str) with reason ("unsupported_date", "api_error", "value")

---

### **EXECUTION & ORDER MANAGEMENT**

73. ⬜ **Paper trading doesn't simulate slippage or fill uncertainty**
    - **Files**: paper.py, main.py
    - **Issue**: Backtests assume mid-price fills; real trades have slippage
    - **Difficulty**: Medium
    - **Solution**: Add slippage model; simulate random partial fills

74. ⬜ **No partial order fills; assumes all-or-nothing**
    - **Issue**: Real market orders might fill incrementally; backtest is unrealistic
    - **Difficulty**: Hard
    - **Solution**: Simulate partial fills based on market depth (if available)

75. ✅ **Execution log stores JSON response as string, not parsed**
    - **Files**: execution_log.py:81
    - **Issue**: Can't query "all failed orders" without parsing string; inefficient
    - **Difficulty**: Easy
    - **Solution**: Store order_status, fill_quantity, error_code in separate columns

76. ✅ **No deduplication check before placing live orders**
    - **Files**: main.py:_auto_place_trades
    - **Issue**: If script crashes and restarts, might place same order twice
    - **Difficulty**: Easy
    - **Solution**: Check was_recently_ordered(ticker, side, within_minutes=10) before placing

77. ✅ **Take-profit targets don't account for fees**
    - **Files**: paper.py:exit_target
    - **Issue**: If exit_target=0.50 and we bought at 0.49, net profit is 0.50 - 0.49 = 0.01, minus 7% fee ≈ 0.0093
    - **Difficulty**: Easy
    - **Solution**: Adjust targets down by fee rate

78. ⬜ **Check exit targets doesn't handle partial fills**
    - **Files**: paper.py:320-350
    - **Issue**: Assumes can sell entire position at market price; real market might not have depth
    - **Difficulty**: Medium
    - **Solution**: Simulate partial fills; check if we can exit within slippage budget

79. ⬜ **No max execution latency enforced**
    - **Issue**: If order takes 30 seconds to place, market might have moved 1–2%
    - **Difficulty**: Medium
    - **Solution**: Add timeout to place_paper_order; abandon if latency > threshold

80. ✅ **Auto-settle doesn't validate that market is truly finalized (status check only)**
    - **Files**: main.py:290-318
    - **Issue**: Kalshi may mark as finalized but later revert; should add delay
    - **Difficulty**: Medium
    - **Solution**: Only settle if status=finalized AND (now - status_change_time) > 1 hour

---

### **WEB DASHBOARD & UI**

81. ⬜ **Dashboard analytics hardcoded to only show 50 most recent balance history points**
    - **Files**: web_app.py:125
    - **Issue**: If running for months, can't see long-term trends
    - **Difficulty**: Easy
    - **Solution**: Add time-range selector (1mo, 3mo, 1yr); query accordingly

82. ✅ **Analyze table sorted only by edge, not filtered by edge threshold**
    - **Files**: web_app.py:353-432
    - **Issue**: Shows all opportunities; MIN_EDGE threshold applied via threshold check, not DB query
    - **Difficulty**: Easy
    - **Solution**: Add MIN_EDGE constant to query; only show opportunities above threshold

83. ✅ **No export functionality for dashboard analytics**
    - **Issue**: Can't download CSV of calibration metrics for external analysis
    - **Difficulty**: Easy
    - **Solution**: Add /api/export endpoint returning CSV of tracker analytics

84. ⬜ **Analytics page doesn't show model attribution (which component adds value)**
    - **Issue**: Can't tell if value comes from climatology, NWS, or ensemble
    - **Difficulty**: Hard
    - **Solution**: Log forecast components during analyze_trade; compute attribution

85. ⬜ **No real-time market updates in web dashboard**
    - **Issue**: Dashboard shows stale prices; must refresh manually
    - **Difficulty**: Medium
    - **Solution**: Implement WebSocket or SSE to push market updates every 10s

86. ✅ **Live dot animation in dashboard blinks but doesn't indicate connection status**
    - **Files**: web_app.py:59
    - **Issue**: User can't tell if SSE stream is actually connected vs broken
    - **Difficulty**: Easy
    - **Solution**: Add "last updated X seconds ago" text; change color if >30s stale

87. ✅ **No dark/light mode toggle (dark is hardcoded)**
    - **Issue**: Early morning trading requires dark mode; afternoon requires light mode
    - **Difficulty**: Easy
    - **Solution**: Add CSS media query for prefers-color-scheme; add toggle button

88. ✅ **Responsive design breaks on mobile (grid layout assumes minimum 2 columns)**
    - **Files**: web_app.py:71
    - **Issue**: On phone, stat cards stack 2x2; unreadable on small screens
    - **Difficulty**: Easy
    - **Solution**: Add @media (max-width: 400px) with 1-column layout

89. ✅ **No pagination for long history tables (e.g., settled trades)**
    - **Files**: web_app.py:188
    - **Issue**: Shows last 10 trades; if 1000 trades exist, can't browse earlier
    - **Difficulty**: Medium
    - **Solution**: Paginate settled trades; add next/prev buttons

90. ✅ **Analyze page refreshes entire list every 60s (stated in HTML but no auto-refresh implemented)**
    - **Files**: web_app.py:415
    - **Issue**: Claims "auto-refreshes every 60s" but doesn't; confuses users
    - **Difficulty**: Easy
    - **Solution**: Implement setInterval(fetch, 60000) to refresh /analyze

---

### **NOTIFICATION & ALERTING**

91. ✅ **Alert system fires but doesn't prevent duplicate alerts**
    - **Files**: alerts.py:90-138
    - **Issue**: If market price is at 0.50 for 1 hour, triggers alert 60+ times
    - **Difficulty**: Easy
    - **Solution**: Mark alert triggered; allow manual re-arm or add cooldown

92. ✅ **Discord webhook hardcoded as single destination**
    - **Files**: notify.py:75-101
    - **Issue**: Can't route different alerts to different channels
    - **Difficulty**: Easy
    - **Solution**: Support multiple webhooks; route by alert severity

93. ✅ **Email notifications silently fail if SMTP credentials are wrong**
    - **Files**: notify.py:104-134
    - **Issue**: No feedback if email doesn't send; user doesn't know
    - **Difficulty**: Easy
    - **Solution**: Log success/failure to tracker; show in dashboard

94. ✅ **Notification templates are hardcoded strings**
    - **Files**: notify.py:137-176
    - **Issue**: Can't customize alert message format; must edit code
    - **Difficulty**: Easy
    - **Solution**: Load templates from data/notify_templates.json; allow customization

95. ✅ **No throttling of notifications**
    - **Issue**: If 5 strong signals fire simultaneously, user gets 5 notifications (spam)
    - **Difficulty**: Medium
    - **Solution**: Batch notifications; send digest every 5 minutes instead of per-signal

96. ✅ **Notification doesn't include recommended position size (Kelly fraction)**
    - **Files**: notify.py:137-149
    - **Issue**: User gets alert but must manually compute Kelly; error-prone
    - **Difficulty**: Easy
    - **Solution**: Include kelly_fraction in notification payload

---

### **PERSISTENCE & DATA MANAGEMENT**

97. ✅ **SQLite database has no indexes on frequently-queried columns**
    - **Files**: tracker.py, execution_log.py
    - **Issue**: get_bias() query scans all predictions; slow on large datasets
    - **Difficulty**: Easy
    - **Solution**: Add indexes on (city, market_date), (condition_type), (method)

98. ✅ **No PRAGMA optimizations for SQLite**
    - **Files**: tracker.py, execution_log.py
    - **Issue**: Default settings are slow; no caching, synchronous mode is full
    - **Difficulty**: Easy
    - **Solution**: Set PRAGMA journal_mode=WAL, synchronous=NORMAL, cache_size=10000

99. ⬜ **Database migrations are manual (ALTER TABLE with try/except)**
    - **Files**: tracker.py:81-86
    - **Issue**: Error-prone; schema version is implicit; hard to track schema evolution
    - **Difficulty**: Medium
    - **Solution**: Implement alembic or similar migration system

100. ✅ **Paper trades JSON file is not schema-versioned**
     - **Files**: paper.py
     - **Issue**: If we add new field (e.g., commission), old trades don't have it; code must handle both
     - **Difficulty**: Easy
     - **Solution**: Add _version field to JSON; auto-migrate on load

101. ✅ **Atomic writes create temporary files in data/ directory**
     - **Files**: paper.py:60-73, alerts.py:28-40
     - **Issue**: If crash during write, .paper_trades_* temp files accumulate; no cleanup
     - **Difficulty**: Easy
     - **Solution**: Add cleanup_temp_files() function; call on startup

102. ⬜ **No data corruption detection (checksums)**
     - **Issue**: If JSON file is partially written, code doesn't detect it
     - **Difficulty**: Medium
     - **Solution**: Add CRC32 or SHA256 field to JSON; validate on load

103. ✅ **Backups are daily text dumps, not point-in-time snapshots**
     - **Files**: main.py:361-394
     - **Issue**: Can't restore to arbitrary date; only have latest + last day's backup
     - **Difficulty**: Medium
     - **Solution**: Implement rotating backups (keep 30 days of daily backups)

104. ⬜ **No automated backup verification**
     - **Issue**: Backup might be corrupt; won't know until disaster strikes
     - **Difficulty**: Medium
     - **Solution**: Verify backup integrity on creation; log checksum

105. ⬜ **Data directory not backed up to cloud**
     - **Issue**: Local disk failure = total loss (unless user manually backs up)
     - **Difficulty**: Medium
     - **Solution**: Implement optional cloud backup (S3, GCS) with encryption

---

### **LOGGING & OBSERVABILITY**

106. ✅ **No structured logging (everything is print statements)**
    - **Files**: main.py (entire file)
    - **Issue**: Can't aggregate logs; can't query "show all errors from 2pm"; can't monitor programmatically
    - **Difficulty**: Medium
    - **Solution**: Replace print with logging module; use JSON format for parseable logs

107. ✅ **Log level is global (all-or-nothing DEBUG vs disabled)**
    - **Files**: main.py:4867
    - **Issue**: Can't set debug for nws.py but info for others
    - **Difficulty**: Easy
    - **Solution**: Use logging.getLogger(__name__) in each module; set per-module levels

108. ✅ **No performance logging (API latency, data processing time)**
    - **Issue**: Don't know if slow performance is API or local code
    - **Difficulty**: Medium
    - **Solution**: Wrap API calls with timing; log latencies > 5s as warning

109. ✅ **Error messages lack context (which ticker? which city?)**
    - **Files**: weather_markets.py, paper.py
    - **Issue**: Log shows "API error" but not which market failed
    - **Difficulty**: Easy
    - **Solution**: Include context in all exception messages (ticker, city, timestamp)

110. ✅ **No audit trail for manual trades**
    - **Files**: main.py:_quick_paper_buy
    - **Issue**: User can place order but no record of why (edge? news? whim?)
    - **Difficulty**: Easy
    - **Solution**: Log user action + rationale to audit table in predictions.db

---

### **TESTING & VALIDATION**

111. ⬜ **No unit tests for core forecasting functions**
     - **Files**: weather_markets.py, climatology.py
     - **Issue**: Hard to refactor confidence intervals or bootstrap without breaking things
     - **Difficulty**: Medium
     - **Solution**: Add pytest tests for ensemble_stats, _bootstrap_ci, analyze_trade edge cases

112. ⬜ **No integration tests for full pipeline**
     - **Issue**: Can't verify that a market flows through enrich → analyze → place_order correctly
     - **Difficulty**: Hard
     - **Solution**: Add integration tests; mock Kalshi API; verify end-to-end

113. ⬜ **No regression tests to catch forecast accuracy degradation**
     - **Issue**: Refactor could silently reduce Brier score by 0.01; wouldn't notice
     - **Difficulty**: Medium
     - **Solution**: Add smoke test that loads historical markets; checks Brier score hasn't changed >1%

114. ✅ **Bootstrap CI doesn't validate that N >= 30**
     - **Files**: weather_markets.py:844-868
     - **Issue**: With N=5 ensemble members, CI is meaningless; no warning
     - **Difficulty**: Easy
     - **Solution**: Return None if N < 30; warn if N < 100

115. ✅ **No validation that Kelly fraction is in [0, 1]**
     - **Files**: weather_markets.py:888-906
     - **Issue**: Edge case where odds are huge can produce f* > 1
     - **Difficulty**: Easy
     - **Solution**: Clamp to [0, 0.25] with warning

116. ✅ **No input validation for analyze_trade**
     - **Issue**: Caller can pass garbage enriched dict; crashes at random points
     - **Difficulty**: Easy
     - **Solution**: Add explicit preconditions; raise ValueError with helpful message

---

### **CONFIGURATION & PARAMETERS**

117. ✅ **Hardcoded thresholds scattered throughout code**
     - **Files**: paper.py, weather_markets.py, main.py
     - **Issue**: MIN_EDGE=0.10, STRONG_EDGE=0.25, etc.; must edit code to change
     - **Difficulty**: Easy
     - **Solution**: Centralize all constants in config.py; load from env or JSON

118. ⬜ **Seasonal model weights are heuristic**
     - **Files**: weather_markets.py:70-80
     - **Issue**: ECMWF weight=2.5 in winter is hardcoded; not validated against data
     - **Difficulty**: Hard
     - **Solution**: Learn weights from backtest; auto-update from walk-forward

119. ✅ **City coordinates are hardcoded**
     - **Files**: weather_markets.py:CITY_COORDS
     - **Issue**: If Kalshi adds a new city, must edit code
     - **Difficulty**: Easy
     - **Solution**: Load from data/cities.json; allow runtime configuration

120. ✅ **No configuration for risk tolerance (Kelly vs fixed-bet strategy)**
     - **Issue**: Kelly is standard but aggressive; some users want fixed 1% per trade
     - **Difficulty**: Easy
     - **Solution**: Add STRATEGY env var (kelly, fixed_pct, fixed_dollars)

121. ✅ **Drawdown tiers are hardcoded**
     - **Files**: paper.py:25-32
     - **Issue**: 50%, 60%, 75%, 90% thresholds are arbitrary; no justification
     - **Difficulty**: Easy
     - **Solution**: Load from config; add documentation

122. ⬜ **No per-city model weighting**
     - **Issue**: NYC might prefer ECMWF; Miami prefers GFS; static weights don't capture
     - **Difficulty**: Medium
     - **Solution**: Load learned_weights per city; use if available

123. ✅ **No configuration for notification channels**
     - **Issue**: All channels enabled by default (Discord, email, plyer); can't disable one
     - **Difficulty**: Easy
     - **Solution**: Add NOTIFY_CHANNELS env var; allow selective enable/disable

---

### **PERFORMANCE & EFFICIENCY**

124. ✅ **Ensemble fetch uses ThreadPoolExecutor with 3 workers hardcoded**
     - **Files**: weather_markets.py:131
     - **Issue**: Assumes 3 models; if API adds 4th model, pool is undersized
     - **Difficulty**: Easy
     - **Solution**: Use len(model_weights) to set max_workers dynamically

125. ✅ **No connection pooling for HTTP requests**
     - **Files**: nws.py, climatology.py, kalshi_client.py
     - **Issue**: Creates new connection for each request; slow if many requests
     - **Difficulty**: Medium
     - **Solution**: Use requests.Session; reuse connections

126. ⬜ **Forecast cache TTL is global (90 min) regardless of forecast age**
     - **Files**: weather_markets.py:97-99
     - **Issue**: A forecast issued at 6am is stale by noon; should refresh at 6pm
     - **Difficulty**: Hard
     - **Solution**: Cache by forecast_cycle; refresh at known times

127. ⬜ **Synchronous API calls block entire market analysis**
     - **Files**: weather_markets.py:507-563
     - **Issue**: Fetches ~200 markets sequentially; takes 1-2 minutes
     - **Difficulty**: Medium
     - **Solution**: Parallelize with ThreadPoolExecutor; fetch 10 markets at a time

128. ✅ **Bootstrap CI resamples N times even if N is huge (e.g., 100k ensemble members)**
     - **Files**: weather_markets.py:844-868
     - **Issue**: With N=100k, bootstrap is slow and overkill
     - **Difficulty**: Easy
     - **Solution**: Cap bootstrap reps at 1000; subsample if N > 10k
