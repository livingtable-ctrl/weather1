# Accuracy Improvement Plan — 2026-04-19

Full inventory of every accuracy gap found across the codebase.
Items are grouped by severity and ordered within each group by expected P&L impact.
Status column: ⬜ = not started · 🔄 = in progress · ✅ = done

---

## Phase A — Critical: built but disconnected (highest immediate impact)

| # | Status | Title | File(s) |
|---|--------|-------|---------|
| A1 | ✅ | Wire `apply_ml_prob_correction()` into `analyze_trade` | `weather_markets.py`, `ml_bias.py` |
| A2 | ✅ | Call `record_feature_contribution()` when every trade is placed | `main.py`, `feature_importance.py` |
| A3 | ✅ | Call `update_outcome()` when every trade settles | `main.py`, `feature_importance.py` |
| A4 | ✅ | Auto-place consistency arbitrage trades (not just display them) | `main.py`, `consistency.py` |
| A5 | ✅ | Run `param_sweep` on startup and write optimal `PAPER_MIN_EDGE` back to config | `param_sweep.py`, `config.py` |

### A1 — Wire `apply_ml_prob_correction()`
**Problem:** `ml_bias.py` trains a GradientBoosting model that predicts
`actual_outcome - our_prob` residuals per city. The model is trained via
`py main.py train-bias` but `apply_ml_prob_correction()` is never called
anywhere in the prediction pipeline. It is dead code.

**Fix:** In `weather_markets.py` → `analyze_trade()`, after the bias
correction block (step 7), add:
```python
from ml_bias import apply_ml_prob_correction
blended_prob = apply_ml_prob_correction(
    city, blended_prob, target_date.month, days_out
)
blended_prob = max(0.01, min(0.99, blended_prob))
```
This fires only when a trained model exists for the city (200+ samples
threshold enforced inside `apply_ml_prob_correction`). No effect until
enough data accumulates; harmless in the meantime.

Also add `py main.py train-bias` to the weekly cron schedule so the model
is retrained as new trades settle.

---

### A2 + A3 — Feature contribution recording
**Problem:** `feature_importance.py` has `record_feature_contribution()` and
`update_outcome()` but neither is ever called. Without this, the analytics
tab "Feature Importance" always shows empty data and you can never learn
which signals (ensemble_spread, model_agreement, days_out, etc.) predict wins.

**Fix:** In `main.py` → `place_paper_order()`, after a trade is accepted:
```python
from feature_importance import record_feature_contribution
record_feature_contribution(ticker, {
    "ensemble_spread": analysis.get("ensemble_spread", 0),
    "model_agreement": 1.0 if analysis.get("model_consensus") else 0.0,
    "days_out": days_out,
    "edge": analysis.get("edge", 0),
    "kelly_fraction": analysis.get("ci_adjusted_kelly", 0),
    "data_quality": analysis.get("data_quality", 0),
    "near_threshold": 1.0 if analysis.get("near_threshold") else 0.0,
})
```
In `main.py` → `cmd_settle()`, after `log_outcome()`:
```python
from feature_importance import update_outcome
update_outcome(ticker, settled_yes=True/False)
```

---

### A4 — Auto-trade consistency arbitrage
**Problem:** `find_violations()` in `consistency.py` correctly detects
impossible market pricings (e.g. `P(high > 70°) > P(high > 65°)`). These
are displayed during `analyze` but never acted on. A violation with
`guaranteed_edge > 0.05` is free money with no forecast risk.

**Fix:** In `main.py` → `_analyze_once()`, after printing violations,
auto-place paper orders for violations where:
- `guaranteed_edge >= 0.05` (worth the fee)
- Both contracts have volume > `MIN_SIGNAL_VOLUME`
- Portfolio exposure for that city is below the risk limit

---

### A5 — Param sweep feedback loop
**Problem:** `param_sweep.py` finds the optimal `PAPER_MIN_EDGE` from
historical trades and saves to `data/param_sweep_results.json`, but nothing
reads that file. The active threshold is always the hardcoded default (5%).

**Fix:** Add a `load_swept_min_edge()` function to `param_sweep.py` that
reads the saved results and returns the value with the best win-rate among
thresholds with ≥ 10 trades. Call it from `config.py` → `load_and_validate()`
as a soft override (env var still takes precedence).

---

## Phase B — High impact: logic flaws in the pipeline

| # | Status | Title | File(s) |
|---|--------|-------|---------|
| B1 | ✅ | MOS uses wrong sigma — replace with MOS-specific RMSE | `weather_markets.py`, `mos.py` |
| B2 | ✅ | Fetch NAM-MOS in addition to GFS-MOS; prefer NAM for days_out=0 | `mos.py`, `weather_markets.py` |
| B3 | ✅ | Add Denver (KDEN) to MOS station list | `mos.py` |
| B4 | ✅ | Split station bias by HIGH vs LOW market (var="max" vs "min") | `weather_markets.py` |
| B5 | ✅ | Relax `get_bias()` stale-data cutoff from 14 days to 60 days | `tracker.py` |
| B6 | ✅ | Move MOS blend to before bias correction, not after | `weather_markets.py` |
| B7 | ✅ | Use `ens_stats["std"]` as sigma in Gaussian fallback when available | `weather_markets.py` |

### B1 — MOS sigma
**Problem:** When MOS fires, probability is computed via
`_forecast_probability(condition, _mos_temp, _forecast_uncertainty(target_date))`.
The sigma is the same generic 3-7°F used everywhere. GFS-MOS verified RMSE
is ~2.5°F at day 1, ~3.2°F at day 2, ~4.0°F at day 3.

**Fix:** Add a `_MOS_SIGMA` lookup by days_out in `mos.py`:
```python
_MOS_GFS_SIGMA = {0: 2.0, 1: 2.5, 2: 3.2, 3: 4.0}  # °F RMSE
_MOS_NAM_SIGMA = {0: 1.8, 1: 2.3}                    # NAM is tighter
```
Pass `mos_data["sigma"]` back from `fetch_mos()` and use it in
`analyze_trade` instead of `_forecast_uncertainty`.

---

### B2 — NAM-MOS for same-day markets
**Problem:** NAM (North American Mesoscale) has 1-hour resolution and runs
4×/day. For `days_out=0` and `days_out=1` markets it outperforms GFS-MOS.
`fetch_mos()` supports `model="NAM"` but is never called with it.

**Fix:** In `analyze_trade`, after the GFS-MOS fetch, add a NAM-MOS fetch
for `days_out <= 1`. Blend: 60% NAM + 40% GFS when both available; fall back
to whichever returns data.

---

### B3 — Denver MOS (one line)
**Problem:** `_CITY_STATION` in `mos.py` is missing `"DEN"`. Denver is your
hardest city to forecast (mountain terrain, 2°F static bias) yet never
benefits from station-specific MOS post-processing.

**Fix:**
```python
_CITY_STATION: dict[str, str] = {
    "NYC": "KNYC",
    "MIA": "KMIA",
    "CHI": "KORD",
    "LAX": "KLAX",
    "DAL": "KDFW",
    "DEN": "KDEN",   # ← add this
}
```

---

### B4 — Split HIGH/LOW station bias
**Problem:** `apply_station_bias()` subtracts the same bias for both the
daily HIGH and daily LOW. Warm biases in GFS are strongest for daytime highs;
overnight lows often have different (sometimes opposite) bias characteristics.
Applying the HIGH bias to a LOW market makes the correction wrong.

**Fix:** Expand `_STATION_BIAS` into `_STATION_BIAS_HIGH` and
`_STATION_BIAS_LOW`, and pass `var` into `apply_station_bias()`:
```python
_STATION_BIAS_HIGH = {"NYC": 1.0, "MIA": 3.0, "DEN": 2.0, "CHI": 0.5, "DAL": 0.5}
_STATION_BIAS_LOW  = {"NYC": 0.5, "MIA": 1.5, "DEN": 1.0, "CHI": 0.0, "DAL": 0.0}

def apply_station_bias(city: str, forecast_temp: float, var: str = "max") -> float:
    table = _STATION_BIAS_HIGH if var == "max" else _STATION_BIAS_LOW
    return forecast_temp - table.get(city.upper(), 0.0)
```
Update the call site in `analyze_trade` to pass `var`.

---

### B5 — Bias staleness window
**Problem:** `get_bias()` returns 0.0 if the most recent settled sample is
>14 days old. With a small trade history (the bot is new), most samples will
often be 2-4 weeks old, making bias correction inactive almost all the time.

**Fix:** Change the stale cutoff from 14 to 60 days. Add a `staleness_weight`
that smoothly reduces the bias impact as data ages (already done with the
30-day exponential decay inside `get_bias`), rather than a hard zero cutoff.

---

### B6 — MOS blend ordering
**Problem:** The pipeline runs:
1. Build `blended_prob` from ensemble + NWS + climatology
2. Apply `get_bias()` bias correction → calibrated `blended_prob`
3. Apply MOS 50/50 blend → final `blended_prob`

Step 3 re-introduces an uncalibrated component after calibration. The bias
correction should apply to the final blended value, not just the pre-MOS value.

**Fix:** Move the MOS blend to before step 2 (bias correction), so the full
blended value (ensemble + NWS + clim + MOS) is bias-corrected together.

---

### B7 — Use ensemble std as Gaussian sigma
**Problem:** When `len(temps) < 10`, the code falls back to
`_forecast_uncertainty(target_date)` (fixed 3-7°F). But `ens_stats` may
still exist with a computed `std` from fewer members. Using actual
ensemble disagreement is better than the generic table.

**Fix:**
```python
if len(temps) >= 10:
    sigma = ens_stats["std"] if ens_stats else _forecast_uncertainty(target_date)
else:
    sigma = (ens_stats["std"] if ens_stats and ens_stats.get("std")
             else _forecast_uncertainty(target_date)) * sigma_mult
```

---

## Phase C — Medium impact: structural improvements

| # | Status | Title | File(s) |
|---|--------|-------|---------|
| C1 | ✅ | Tighten `MAX_MODEL_SPREAD_F` from 8.0°F to 5.5°F | `.env` (env var, no code change) |
| C2 | ✅ | Require all 3 sources for consensus bonus (not just 2) | `weather_markets.py` |
| C3 | ✅ | Hard-skip trades when regime is "volatile" (std > 12°F) | `weather_markets.py` |
| C4 | ✅ | Reduce `MAX_DAYS_OUT` from 5 to 2 (or 3 max) | `.env` (env var, no code change) |
| C5 | ✅ | Reduce calibration grid step from 5% to 1% | `calibration.py` |
| C6 | ✅ | Add `ABTest` for `MIN_EDGE` variants (0.05 / 0.07 / 0.09) | `main.py`, `ab_test.py` |

### C1 — Tighter model spread gate
At 8°F spread, your two primary models (GFS, ICON) disagree by a full
temperature tier. The probability estimate is nearly meaningless.
Set `MAX_MODEL_SPREAD_F=5.5` via env var — no code change needed.

### C2 — Consensus requires all 3 sources
Current code: `consensus = len(sources_with_data) >= 2 and all agree`.
With only NWS + ensemble agreeing, that's 2 sources with similar methodology
(both use GFS). Climatology is an independent signal. Change to
`len(sources_with_data) >= 3` to require genuine independence.

### C3 — Skip volatile regime entirely
`regime.py` correctly identifies chaos (std > 12°F) and applies a 0.80x
Kelly reduction. But you're still trading. Add a hard return in `analyze_trade`
when `_regime_info["regime"] == "volatile"`:
```python
if _regime_info.get("regime") == "volatile":
    return None  # skip — models are in chaos
```

### C4 — Reduce MAX_DAYS_OUT
Set `MAX_DAYS_OUT=2` in `.env`. This alone removes your worst-performing
trades (days 3-5 where sigma is 5-7.5°F and blend is mostly climatology).
Run `py main.py sweep` first to confirm the optimal cutoff from your data.

### C5 — Finer calibration grid
Change `_WEIGHT_STEP = 0.05` to `_WEIGHT_STEP = 0.01` in `calibration.py`.
Combinations grow from 231 to 5,151 — still runs in <1 second on modern
hardware. Finds weights like (0.71, 0.12, 0.17) that the coarse grid misses.

### C6 — A/B test MIN_EDGE
Instantiate an `ABTest` for `PAPER_MIN_EDGE` with variants
`{"low": 0.05, "medium": 0.07, "high": 0.09}` in the auto-scan path.
After 50 trades per variant, the loser is auto-disabled. This is the
correct way to find the optimal edge threshold empirically.

---

## Phase D — Lower lift: data quality

| # | Status | Title | File(s) |
|---|--------|-------|---------|
| D1 | ✅ | Give ECMWF higher weight in `model_temps` Gaussian blend | `weather_markets.py` |
| D2 | ✅ | Add winter/summer sigma split to `_HISTORICAL_SIGMA` | `weather_markets.py` |
| D3 | ✅ | Fix persistence baseline: use today's observed max, not current temp | `weather_markets.py` |
| D4 | ✅ | Feed `backtest` walk-forward optimal params back to config | `backtest.py`, `config.py` |
| D5 | ✅ | Add `train-bias` to weekly cron (Sunday 02:00 UTC) | `cron.py` |
| D6 | ✅ | Lower calibration minimum samples: 50 seasonal → 20, 30 city → 15 | `calibration.py` |

### D1 — ECMWF weight in Gaussian blend
`model_temps = {"nbm": ..., "ecmwf": ...}` — both get equal weight in the
raw fraction calculation. ECMWF is ~20% more accurate than GFS at 1-3 days.
Weight ECMWF 2× NBM in the `raw_fraction` calculation:
```python
weighted_temps = {m: (v, 2.0 if m == "ecmwf" else 1.0)
                  for m, v in model_temps.items() if v is not None}
```

### D2 — Seasonal sigma
`_HISTORICAL_SIGMA` has 4 seasons but uses integer keys (1=winter through
4=fall). Summer in cities like DEN and CHI has much tighter predictability
than winter. Add summer-specific sigma values where known.

### D3 — Persistence baseline fix
In the persistence calculation for `days_out=0`, `_current_temp` is set to
`_live["temp_f"]` — the instantaneous current temperature. For high-temp
markets this is wrong after noon (the high has already occurred and is
higher than the current reading). Should use `_live.get("max_temp_f")`
or `_live.get("high_f")` if the observation includes today's max.

### D4 — Walk-forward feedback
`backtest.py` → `walk_forward_backtest()` computes optimal `PAPER_MIN_EDGE`
and `MAX_DAYS_OUT` per time window. Add a `save_walk_forward_params()` that
writes results to `data/walk_forward_params.json`. Then `config.py` reads
this file as a soft override (env var takes precedence).

### D5 — Cron: weekly train-bias
Add to `cron.py` scheduled tasks:
```python
# Weekly: retrain ML bias model as new trades settle
schedule.every().sunday.at("02:00").do(cmd_train_bias, client)
```

### D6 — Lower calibration thresholds
`_SEASONAL_MIN = 50` and `_CITY_MIN = 30` mean calibration weights won't
fire until you have hundreds of trades. Lower to 20 seasonal / 15 city so
you start getting data-driven weights much sooner. The grid-search is still
valid at smaller sample sizes; it just has higher variance, which is fine
when the alternative is hardcoded guesses.

---

## Implementation order (recommended)

```
Phase A → Phase B (B3 first, it's 1 line) → C4, C1 (env var changes) → rest of C → D
```

Start with **B3** (add DEN to MOS — 1 line, instant win) and **A1** (wire
`apply_ml_prob_correction` — 5 lines, biggest long-term payoff). Then **C4**
(reduce MAX_DAYS_OUT — 1 env var, stops bad trades immediately).

---

## Expected impact summary

| Phase | Trades affected | Mechanism |
|-------|----------------|-----------|
| A1 — ML bias correction | All trades, post 200 settled | Learned probability calibration |
| A4 — Arbitrage auto-trade | ~1-3/week when market misprices | Near risk-free edge |
| B3 — Denver MOS | All DEN trades | Extra signal source |
| B4 — HIGH/LOW bias split | ~50% of LOW trades | Correct direction of correction |
| B5 — Bias staleness fix | Most cities early stage | Bias actually fires |
| C3 — Skip volatile | ~5% of days | Stops the worst-case gambles |
| C4 — MAX_DAYS_OUT=2 | Removes days 3-5 trades | Eliminates lowest-accuracy segment |
| C6 — A/B test MIN_EDGE | All paper trades | Empirically finds best threshold |

Total: **24 items across 4 phases.**
