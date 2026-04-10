# Model Signal Calibration Design

**Date:** 2026-04-10
**Goal:** Sharpen the edge signal and blend weights by using historical backtest data rather than heuristics — covering horizon-adjusted edge confidence (#63), seasonal blend weight optimization (#118), and per-city blend weight optimization (#122).

---

## Problem

Three related weaknesses in the current signal pipeline:

1. **Edge doesn't decay with forecast horizon (#63).** A 12% edge on day 1 and a 12% edge on day 12 pass the same MIN_EDGE filter, but day-12 edge is noisier — model uncertainty compounds over time and the market has more time to correct. Only Kelly size currently varies with days_out; the go/no-go signal does not.

2. **Seasonal blend weights are hardcoded (#118).** `_blend_weights()` uses a fixed NWS/ensemble/climatology schedule based only on days_out. NWS performs differently in summer (convective uncertainty) vs. winter (frontal systems are more predictable); ensemble models do too. Optimal weights should come from settled prediction history.

3. **Per-city blend weights are missing (#122).** NYC has dense NWS coverage and a long prediction history; a smaller Sun Belt city may have less reliable NWS data. All cities currently use identical weights.

---

## Architecture

Three targeted additions across two files, plus one new file:

- `calibration.py` (NEW) — offline grid-search calibration + runtime loaders
- `tracker.py` — schema migration v7 adding `ensemble_prob`, `nws_prob`, `clim_prob` columns; updated `log_prediction()` signature
- `weather_markets.py` — `edge_confidence()` function, updated `_blend_weights()` priority logic, module-level calibration load, pass per-source probs to `log_prediction()`
- `main.py` — `calibrate` CLI command
- `tests/test_calibration.py` (NEW) — 5 tests
- `tests/test_weather_markets.py` — 2–3 new tests for `edge_confidence()`

---

## Design

### 1. `edge_confidence(days_out: int) -> float`

New function in `weather_markets.py`. Piecewise linear multiplier applied to `net_edge` before the MIN_EDGE filter, go/no-go signal, and EV score ranking. Does **not** affect Kelly size (already has its own `time_kelly_scale`).

```
days_out  multiplier
0–2       1.00  (full confidence — forecast is most accurate)
3–7       linear 1.00 → 0.80
8–14      linear 0.80 → 0.60
>14       0.60  (floor — highly uncertain horizon)
```

Formula for the linear segments:
- 3–7: `1.0 - (days_out - 2) / 5.0 * 0.20`
- 8–14: `0.80 - (days_out - 7) / 7.0 * 0.20`

Applied in `analyze_trade()`:
```python
confidence = edge_confidence(days_out)
adjusted_edge = net_edge * confidence
```

`adjusted_edge` replaces `net_edge` in the MIN_EDGE comparison and signal output. Both raw and adjusted edge are included in the returned analysis dict so the dashboard can display both.

### 2. `calibration.py` — Seasonal weights (#118)

#### `calibrate_seasonal_weights(db_path: str | Path) -> dict`

Reads all settled predictions from the DB (joined with outcomes), groups by season:
- Winter: Dec, Jan, Feb
- Spring: Mar, Apr, May
- Summer: Jun, Jul, Aug
- Fall: Sep, Oct, Nov

**Prerequisite — schema migration:** The current DB stores `blend_sources` (the weights used) but not the individual per-source probabilities. Without those, grid-search is impossible. A new schema migration (v7) adds three columns to `predictions`:

```sql
ALTER TABLE predictions ADD COLUMN ensemble_prob REAL;
ALTER TABLE predictions ADD COLUMN nws_prob REAL;
ALTER TABLE predictions ADD COLUMN clim_prob REAL;
```

`analyze_trade()` is updated to pass these to `tracker.log_prediction()`, which stores them alongside `our_prob`. Calibration only runs on rows where all three columns are non-NULL (i.e., predictions logged after the migration).

For each season with ≥ 50 settled predictions that have per-source probs, grid-searches `(w_ensemble, w_climatology, w_nws)` combinations in 0.05 steps where all three sum to 1.0, evaluating each combo by Brier score:

```
brier = mean((w_e * ensemble_prob + w_c * clim_prob + w_n * nws_prob - settled_yes)^2)
```

Picks the combo minimizing Brier. If a season has < 50 qualifying predictions, that season is omitted from the output (falls back to hardcoded defaults at runtime).

Writes result to `data/seasonal_weights.json`:
```json
{
  "winter": {"ensemble": 0.55, "climatology": 0.25, "nws": 0.20},
  "summer": {"ensemble": 0.45, "climatology": 0.20, "nws": 0.35}
}
```

#### `load_seasonal_weights() -> dict`

Reads `data/seasonal_weights.json`. Returns `{}` if file missing. Called once at module load in `weather_markets.py`.

### 3. `calibration.py` — Per-city weights (#122)

#### `calibrate_city_weights(db_path: str | Path) -> dict`

Same grid-search approach, grouped by city. Requires ≥ 30 settled predictions per city (lower threshold since cities accumulate data more slowly). Writes to `data/city_weights.json`:
```json
{
  "NYC": {"ensemble": 0.60, "climatology": 0.15, "nws": 0.25},
  "Chicago": {"ensemble": 0.50, "climatology": 0.20, "nws": 0.30}
}
```

#### `load_city_weights() -> dict`

Reads `data/city_weights.json`. Returns `{}` if file missing.

### 4. `_blend_weights()` priority logic

Updated lookup order in `weather_markets.py`:

1. **City-specific weights** — if city present in `city_weights` dict (loaded at startup)
2. **Seasonal weights** — if current month's season present in `seasonal_weights` dict
3. **Existing hardcoded schedule** — always available as final fallback

The existing days_out interpolation within the hardcoded schedule is preserved for the fallback case. City and seasonal weights are flat (not days_out dependent) since they're derived from aggregated history across all horizons.

### 5. `python main.py calibrate` CLI command

New command in `main.py`. Calls both `calibrate_seasonal_weights` and `calibrate_city_weights` with the configured DB path, prints a summary comparing output weights vs. hardcoded defaults, and reports how many predictions were used per season/city.

Example output:
```
Seasonal calibration (from 312 settled predictions):
  winter: nws 0.20→0.28, ensemble 0.55→0.52, clim 0.25→0.20  (n=84)
  summer: nws 0.35→0.41, ...  (n=97)
  spring: insufficient data (n=31, need 50) — using hardcoded

City calibration (from 312 settled predictions):
  NYC:     nws 0.25→0.30  (n=78)
  Chicago: insufficient data (n=18, need 30) — using hardcoded
```

---

## Fallback and Safety

- If either JSON file is missing at startup, `weather_markets.py` logs a debug message and uses hardcoded weights — no crash, no warning to the user.
- If a city or season is missing from the loaded dicts, falls back silently.
- Grid search is purely read-only on the DB; `calibrate` command never writes trades or predictions.
- `edge_confidence()` floor of 0.60 ensures far-out markets with strong enough raw edge (e.g., 20%+ raw → 12% adjusted) still pass MIN_EDGE = 7%.

---

## Testing

**`tests/test_calibration.py`** — 5 tests:
1. `test_calibrate_seasonal_returns_weights_summing_to_one` — seed tmp DB with 60+ winter predictions including per-source probs, verify output weights sum to 1.0 and each in [0, 1]
2. `test_calibrate_seasonal_below_threshold_omits_season` — seed with 30 predictions (< 50), verify season absent from output
3. `test_calibrate_seasonal_skips_rows_without_source_probs` — seed with 60 rows but only 20 have per-source probs, verify season omitted (< 50 qualifying)
4. `test_calibrate_city_returns_weights_for_qualifying_city` — seed with 35 NYC predictions with per-source probs, verify NYC present in output
5. `test_calibrate_city_below_threshold_omits_city` — seed with 20 predictions, verify city absent

**`tests/test_weather_markets.py`** — 3 new tests in `TestEdgeConfidence`:
1. `test_edge_confidence_day_0_is_1` — days_out=0 → 1.0
2. `test_edge_confidence_day_14_is_0_60` — days_out=14 → 0.60
3. `test_edge_confidence_floor_at_day_20` — days_out=20 → 0.60 (floor, not below)

---

## Risk Constants Summary

| Parameter | Before | After | Rationale |
|-----------|--------|-------|-----------|
| Edge at day 0 | raw edge | raw edge × 1.0 | unchanged |
| Edge at day 7 | raw edge | raw edge × 0.88 | moderate horizon discount |
| Edge at day 14+ | raw edge | raw edge × 0.60 | high uncertainty floor |
| Blend weights | hardcoded | calibrated from history, hardcoded fallback | data-driven, safe degradation |

---

## Out of Scope

- Real-time weight recalibration (weights update at most weekly via `calibrate` command)
- Separate weights per condition type (above/below/precip) — too sparse per city × condition × season cell
- Changing the Kelly `time_kelly_scale` formula — it already handles position sizing correctly
