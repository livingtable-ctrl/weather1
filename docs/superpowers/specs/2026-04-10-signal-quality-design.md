# Signal Quality Design

**Date:** 2026-04-10
**Goal:** Sharpen signal accuracy and position sizing by stratifying four decisions — bias correction, edge confidence, ensemble weighting, and Kelly sizing — by condition type and forecast recency.

---

## Problem

Four related gaps cause the signal pipeline to treat all markets identically when they should be treated differently:

1. **Bias correction ignores condition type (#10).** `get_bias()` accepts a `condition_type` parameter but `analyze_trade()` never passes it. A precip market and a temperature market in the same city/month get the same historical bias correction even though their forecast biases are structurally different.

2. **Edge confidence ignores condition type (#14).** `edge_confidence(days_out)` applies the same horizon discount regardless of whether the market is temperature or precipitation. Precipitation forecasts have higher irreducible uncertainty at every horizon — an above/below temperature edge at day 7 is more reliable than a precip edge at day 7.

3. **Ensemble MAE uses all history equally (#25).** `get_member_accuracy()` averages MAE over the full database. Models drift — ECMWF outperforms GFS in some seasons and vice versa. Weights should reflect recent performance, not career averages.

4. **Kelly sizing ignores condition type (#39).** `ci_adjusted_kelly` scales by horizon (`time_kelly_scale`) but not by condition type. A snow market passes the same go/no-go filter and gets the same fractional bet as a temperature market with identical raw edge.

---

## Architecture

Two files modified, no schema changes, one new test file.

| Feature | File | Change |
|---------|------|--------|
| #10 Bias by condition | `weather_markets.py` | Pass `condition_type` to `get_bias()` in `analyze_trade()` |
| #14 Edge decay by condition | `weather_markets.py` | `edge_confidence(days_out, condition_type=None)` + `_CONDITION_CONFIDENCE` table |
| #25 Recent-MAE weighting | `tracker.py` + `weather_markets.py` | `get_member_accuracy(days_back=60)` date filter; `_weights_from_mae()` passes it through |
| #39 Kelly by condition | `weather_markets.py` | `condition_type_scale` factor in `ci_adjusted_kelly` |
| Tests | `tests/test_signal_quality.py` | 6 new tests |

---

## Design

### 1. #10 — Bias correction by condition type

`get_bias()` in `tracker.py` already has a `condition_type` parameter with a fallback to global bias when fewer than `min_samples=5` qualifying predictions exist. The only change is in `analyze_trade()`:

```python
# Before
bias = get_bias(city, target_date.month)

# After
bias = get_bias(city, target_date.month, condition_type=condition_type)
```

`condition_type` is already in scope at that point in `analyze_trade()`. No other changes. If insufficient condition-specific history exists, `get_bias()` falls back to the global bias automatically.

---

### 2. #14 — Edge decay by condition type

New module-level constant in `weather_markets.py`:

```python
_CONDITION_CONFIDENCE: dict[str, float] = {
    "above": 1.00,
    "below": 1.00,
    "between": 1.00,
    "precip_any": 0.90,
    "precip_above": 0.85,
    "precip_snow": 0.80,
}
```

Rationale: precipitation forecasts have higher irreducible uncertainty than temperature at every horizon. Snow requires two thresholds to be met (precip AND temperature), making it the hardest. Temperature above/below is the baseline.

Updated `edge_confidence`:

```python
def edge_confidence(days_out: int, condition_type: str | None = None) -> float:
    """Horizon + condition discount factor for edge signal.

    Combines the existing piecewise horizon discount with a per-condition
    multiplier. Precipitation and snow markets are inherently harder to
    forecast, so their effective edge is discounted further.
    """
    if days_out <= 2:
        horizon = 1.0
    elif days_out <= 7:
        horizon = 1.0 - (days_out - 2) / 5.0 * 0.20
    elif days_out <= 14:
        horizon = 0.80 - (days_out - 7) / 7.0 * 0.20
    else:
        horizon = 0.60
    cond = _CONDITION_CONFIDENCE.get(condition_type or "", 1.0)
    return round(horizon * cond, 4)
```

`analyze_trade()` updated:

```python
_edge_conf = edge_confidence(days_out, condition_type=condition_type)
```

The effective floor for a snow market (`precip_snow`) at days_out > 14: `0.60 × 0.80 = 0.48`. This means a snow market needs a raw edge of at least `MIN_EDGE / 0.48 ≈ 14.6%` to pass (assuming `MIN_EDGE = 0.07`), versus `0.07 / 0.60 ≈ 11.7%` for temperature markets. Stronger signal required to enter precip/snow.

---

### 3. #25 — Recent-MAE ensemble weighting

`get_member_accuracy()` in `tracker.py` gets a `days_back` parameter:

```python
def get_member_accuracy(days_back: int = 60) -> dict:
    """Return per-model accuracy stats filtered to recent predictions.

    days_back=60 captures ~one season transition while giving each model
    enough observations (daily scoring ≈ 60 data points per city per model).
    """
    init_db()
    with _conn() as con:
        rows = con.execute(
            """
            SELECT model, city, predicted_temp, actual_temp
            FROM ensemble_member_scores
            WHERE logged_at >= datetime('now', ? || ' days')
            """,
            (f"-{days_back}",),
        ).fetchall()
```

`_weights_from_mae()` in `weather_markets.py` passes `days_back=60`:

```python
def _weights_from_mae(city: str, min_n: int = 20, days_back: int = 60) -> dict[str, float] | None:
    accuracy = get_member_accuracy(days_back=days_back)
    ...
```

If a model has fewer than `min_n=20` recent scores, `_weights_from_mae` returns `None` and the existing equal-weights fallback applies. No calibration file changes — this is purely dynamic at runtime.

**Default window:** 60 days. Captures one season transition, provides ~60 daily observations per model per city. Short enough to reflect recent drift; long enough for statistical reliability.

---

### 4. #39 — Kelly sizing by condition type

The same `_CONDITION_CONFIDENCE` table from #14 is applied as a `condition_type_scale` factor in `ci_adjusted_kelly`:

```python
condition_type_scale = _CONDITION_CONFIDENCE.get(condition_type or "", 1.0)

ci_adjusted_kelly = round(
    bk
    * quality_scale
    * anomaly_scale
    * spread_scale
    * time_kelly_scale
    * _confidence_boost
    * condition_type_scale,   # new
    6,
)
```

This produces a compound effect: a snow market with `condition_type_scale=0.80` not only requires stronger raw edge to pass MIN_EDGE — it also bets 20% smaller when it does pass. Both effects use the same multiplier table, keeping the system internally consistent.

The cap `min(ci_adjusted_kelly, 0.25)` still applies after the condition scale.

---

## Fallback and Safety

- **#10**: If `condition_type` is `None` or has no history, `get_bias()` returns global bias — identical to current behavior.
- **#14**: If `condition_type` is unknown/None, `_CONDITION_CONFIDENCE.get(condition_type or "", 1.0)` returns 1.0 — identical to current behavior.
- **#25**: If fewer than `min_n=20` recent scores exist for a model, `_weights_from_mae` returns `None` — falls back to equal weighting as today.
- **#39**: If `condition_type` is None, `condition_type_scale=1.0` — identical to current Kelly behavior.

All four changes degrade gracefully to today's behavior when data is insufficient.

---

## Testing

**`tests/test_signal_quality.py`** — 6 new tests:

1. `test_edge_confidence_precip_snow_lower_than_temp` — same `days_out=5`, `condition_type="precip_snow"` produces lower value than `condition_type="above"`
2. `test_edge_confidence_condition_compounds_horizon` — `days_out=10, condition_type="precip_snow"`: horizon=`0.80 - (3/7)*0.20 ≈ 0.7143`, × 0.80 ≈ `0.5714`
3. `test_edge_confidence_unknown_condition_defaults_to_one` — `condition_type="unknown"` → same as no condition_type
4. `test_bias_correction_passes_condition_type` — mock `tracker.get_bias`, call `analyze_trade()` with a precip ticker, assert `get_bias` called with `condition_type` kwarg
5. `test_get_member_accuracy_respects_days_back` — seed `ensemble_member_scores` with old (90 days ago) and recent (10 days ago) rows; `get_member_accuracy(days_back=60)` returns only recent rows
6. `test_kelly_lower_for_precip_snow` — construct two identical analyses differing only in `condition_type`; snow produces lower `ci_adjusted_kelly`

---

## Risk Constants Summary

| Parameter | Before | After | Rationale |
|-----------|--------|-------|-----------|
| Bias correction | global per city/month | per city/month/condition | More precise historical calibration |
| Edge confidence (precip_any) | horizon only | horizon × 0.90 | Precip harder to forecast |
| Edge confidence (precip_snow) | horizon only | horizon × 0.80 | Snow hardest — two thresholds |
| Kelly (precip_snow) | full fraction | fraction × 0.80 | Size down when signal is noisier |
| MAE window | all history | last 60 days | Capture model drift, recent season |

---

## Out of Scope

- Per-condition-type MAE for NWS and climatology (insufficient per-source scoring data)
- Condition-type weights in `calibrate_seasonal_weights` / `calibrate_city_weights` — too sparse per cell
- Changing `_CONDITION_CONFIDENCE` values based on backtested history — hardcoded for now, revisited in Group 5 post-mortem
