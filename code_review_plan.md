# Plan: Comprehensive Code Review Fixes + Feature Implementation

## Context
Full senior code review identified 11 P0/P1 bugs (several causing silent financial-risk failures), 6 P2 issues, 4 P3 cleanup items, and 3 high-ROI features. This plan implements all of them in priority order using the best available solution for each.

---

## Phase 1 — P0: Critical Fixes (financial safety)

### P0-1 · Settlement uses `entry_price` not `actual_fill_price`
**File:** `paper.py:640-658`  
**Fix:** In `settle_paper_trade`, replace `entry_price = t["entry_price"]` with `entry_price = t.get("actual_fill_price") or t["entry_price"]` and recompute `cost = entry_price * qty`. This makes P&L consistent with the slippage-adjusted fill stored on the trade.

### P0-2 · Daily loss limit uses entry date, not settlement date
**File:** `paper.py:655-658, 1490-1495`  
**Fix (two parts):**
1. In `settle_paper_trade`, add `t["settled_at"] = datetime.now(UTC).isoformat()` alongside `t["settled"] = True`.
2. In `get_daily_pnl`, change the filter to `t.get("settled_at", t.get("entered_at", ""))[:10] == today_str`. This ensures today's settled losses always hit the daily cap regardless of when the trade was entered.  
**Also:** update `get_current_streak` (`paper.py:1403`) to sort by `settled_at` instead of `entered_at`.

### P0-3 · Duplicate `_LEARNED_WEIGHTS_TTL_DAYS` + no mtime refresh
**File:** `weather_markets.py:1311-1314, 1317-1340`  
**Fix (two parts):**
1. Delete the duplicate line 1314.
2. In `load_learned_weights()`, after the `if _LEARNED_WEIGHTS: return` guard, add an mtime check: if the file mtime is newer than when the cache was populated, clear `_LEARNED_WEIGHTS` and reload. Store `_LEARNED_WEIGHTS_LOADED_AT: float = 0.0` at module level. Update it on every successful load.

```python
_LEARNED_WEIGHTS: dict = {}
_LEARNED_WEIGHTS_LOADED_AT: float = 0.0
_LEARNED_WEIGHTS_TTL_DAYS = 7

def load_learned_weights() -> dict:
    global _LEARNED_WEIGHTS, _LEARNED_WEIGHTS_LOADED_AT
    path = Path(__file__).parent / "data" / "learned_weights.json"
    if _LEARNED_WEIGHTS and path.exists():
        if os.path.getmtime(path) <= _LEARNED_WEIGHTS_LOADED_AT:
            return _LEARNED_WEIGHTS
        _LEARNED_WEIGHTS = {}  # file updated — reload
    # ... existing load logic ...
    _LEARNED_WEIGHTS_LOADED_AT = time.time()
    return _LEARNED_WEIGHTS
```

### P0-4 · Exposure limits use `STARTING_BALANCE` forever
**File:** `paper.py:820-862` (5 functions)  
**Fix:** Replace `/ STARTING_BALANCE` with `/ max(STARTING_BALANCE, get_balance())` in `get_city_date_exposure`, `get_directional_exposure`, `get_total_exposure`, `get_ticker_exposure`, and `get_correlated_exposure`. This keeps caps meaningful during drawdown while allowing proper deployment as balance grows.

### P0-5 · Near-extreme price markets inflate `net_edge`
**File:** `weather_markets.py:89`  
**Fix:** Raise `MIN_MARKET_PRICE` default from `0.05` to `0.08`. Already an env-var override so no hardcoding. This is the root cause fix — blocking the problematic markets at the gate rather than adding another cap downstream.
```python
MIN_MARKET_PRICE: float = float(os.getenv("MIN_MARKET_PRICE", "0.08"))
```

---

## Phase 2 — P1: High-Priority Logic Fixes

### P1-1 · `_weights_from_mae` city count bug
**File:** `weather_markets.py:1475`  
**Fix:** Remove city-level MAE entirely until tracker exposes per-city sample counts. Replace with global MAE always:
```python
# city_n check was counting total cities in dict, not samples for this city
mae = stats["mae"]
```
This is safer than a broken city-level override.

### P1-2 · Calibration grid search blocks cron
**File:** `calibration.py:57-80`  
**Fix:** Replace `_best_weights` grid search with `scipy.optimize.minimize` (L-BFGS-B). Parameterize as `(e, c)` with `n = 1 - e - c`, bounds `[0,1]` for both. Falls back to existing grid search if scipy unavailable.
```python
def _best_weights(rows):
    try:
        from scipy.optimize import minimize
        def neg_brier(x):
            e, c = x; n = 1.0 - e - c
            if n < 0: return 1e9
            return _brier(rows, e, c, n)
        res = minimize(neg_brier, [0.4, 0.3], method="L-BFGS-B",
                       bounds=[(0,1),(0,1)])
        e, c = res.x; n = max(0.0, 1.0 - e - c)
        return {"ensemble": round(e,4), "climatology": round(c,4), "nws": round(n,4)}
    except ImportError:
        pass
    # fallback: existing grid search
    ...
```

### P1-3 · `consistency.py` arbitrage never executed in cron
**File:** `cron.py` (`_cmd_cron_body`)  
**Fix:** After the market fetch, call `find_violations(markets)`. For each violation with `guaranteed_edge > 0.05`, synthesize a signal dict and append it to `strong_opps` with `signal="ARBITRAGE"` and the `buy_ticker`. Since we cannot short paper trades, only the long leg is placed.
```python
from consistency import find_violations
violations = find_violations(markets)
for v in violations:
    if v.guaranteed_edge > 0.05:
        arb_signal = {"ticker": v.buy_ticker, "signal": "ARBITRAGE",
                      "guaranteed_edge": v.guaranteed_edge, ...}
        strong_opps.insert(0, arb_signal)  # highest priority
```
Needs a lightweight `_build_arb_opp` helper that constructs the opp dict from a `Violation`.

### P1-4 · Morning observations corrupt same-day HIGH markets
**File:** `weather_markets.py:3766` and `nws.py:363`  
**Fix:** In the `obs_override` block at `weather_markets.py:3766`, add a noon gate for `var == "max"` markets:
```python
if days_out == 0 and condition.get("type") != "between":
    # For daily-high markets, obs before noon local time is misleading —
    # the high hasn't occurred yet and current temp dominates the blend.
    _skip_early_obs = False
    if var == "max":
        try:
            import pytz as _pytz
            _tz_name = coords[2] if len(coords) > 2 else "UTC"
            _local_hour = datetime.now(_pytz.timezone(_tz_name)).hour
            _skip_early_obs = _local_hour < 13  # before 1 PM local
        except Exception:
            pass
    if not _skip_early_obs:
        try:
            live_obs = get_live_observation(city, coords)
            ...
```
`pytz` is already used in the codebase. If unavailable, gate defaults to allowing obs (fail-open).

### P1-5 · Unbounded module-level cache dicts (memory leak)
**File:** `weather_markets.py:661-662, 2719-2720`  
**Fix:** Replace all three plain dicts with `ForecastCache` instances, matching the existing pattern:
```python
# was: _NBM_CACHE: dict[tuple, tuple[float | None, float]] = {}
_NBM_CACHE: ForecastCache[tuple[float | None, float]] = ForecastCache(ttl_secs=4 * 3600)
_ECMWF_CACHE: ForecastCache[tuple[float | None, float]] = ForecastCache(ttl_secs=4 * 3600)
_CONSENSUS_CACHE: ForecastCache[tuple] = ForecastCache(ttl_secs=4 * 3600)
```
Update all read/write call sites to use `ForecastCache.get(key)` / `ForecastCache.set(key, value)` API. Check how `_ensemble_cache` and `_forecast_cache` use the API and mirror exactly.

---

## Phase 3 — P2: Medium-Priority Correctness

### P2-1 · Streak sort uses `entered_at`
**File:** `paper.py:1403`  
**Fix:** After P0-2 adds `settled_at`, update sort key:
```python
settled.sort(key=lambda t: t.get("settled_at") or t.get("entered_at", ""))
```

### P2-2 · `clim_prior = 0.30` hardcoded for precipitation
**File:** `weather_markets.py:2995-2996`  
**Fix:** Add a `_PRECIP_CLIM_RATES` lookup table using NOAA 30-year average daily precipitation frequency per city per season. Replace the hardcoded 0.30:
```python
_PRECIP_CLIM_RATES: dict[str, dict[str, float]] = {
    # city: {season: P(precip on random day)}
    "New York": {"winter": 0.38, "spring": 0.37, "summer": 0.35, "fall": 0.35},
    "Los Angeles": {"winter": 0.18, "spring": 0.10, "summer": 0.02, "fall": 0.08},
    "Chicago": {"winter": 0.35, "spring": 0.38, "summer": 0.35, "fall": 0.33},
    "Houston": {"winter": 0.32, "spring": 0.38, "summer": 0.42, "fall": 0.35},
    "Phoenix": {"winter": 0.15, "spring": 0.10, "summer": 0.25, "fall": 0.12},
    "Seattle": {"winter": 0.60, "spring": 0.48, "summer": 0.20, "fall": 0.52},
    # ... remaining cities from _CITY_COORDS ...
}
_PRECIP_CLIM_DEFAULT = 0.30  # fallback

def _precip_clim_prior(city: str, target_month: int) -> float:
    season = _MONTH_TO_SEASON.get(target_month, "spring")
    return _PRECIP_CLIM_RATES.get(city, {}).get(season, _PRECIP_CLIM_DEFAULT)
```
Then: `clim_prior = _precip_clim_prior(city, target_month)`.  
Use `_MONTH_TO_SEASON` from `calibration.py` or define locally.

### P2-3 · `_score_ensemble_members` trains on fake temperatures
**File:** `paper.py:724-738`  
**Fix:** Remove the synthetic `threshold ± 3°F` proxy entirely. Only call `log_member_score` when a real METAR actual temperature is available via `get_live_observation`. If no real observation is available at settlement time, skip scoring for that trade — it's better to have fewer, accurate training samples than many fabricated ones.
```python
def _score_ensemble_members(trade: dict, outcome_yes: bool) -> None:
    city = trade.get("city")
    # Only score if we have a real observed temperature, not a proxy
    try:
        from nws import get_live_observation
        coords = _CITY_COORDS.get(city, ())
        obs = get_live_observation(city, coords) if coords else None
        actual_temp = obs.get("temp_f") if obs else None
    except Exception:
        actual_temp = None
    if actual_temp is None:
        return  # don't train on fabricated data
    # ... existing model scoring logic with real actual_temp ...
```

### P2-4 · `ml_bias.py` loads pickle without integrity check
**File:** `ml_bias.py:23-30`  
**Fix:** Store a SHA-256 hash sidecar file `bias_models.pkl.sha256` when saving. On load, verify hash before unpickling. If hash missing or mismatched, log warning and return empty (degrade gracefully — bias correction is optional).
```python
import hashlib
def _verify_pickle(path: Path) -> bool:
    hash_path = path.with_suffix(".pkl.sha256")
    if not hash_path.exists():
        return True  # legacy file, skip check
    expected = hash_path.read_text().strip()
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    return actual == expected
```

### P2-5 · `check_exit_targets` partial fill is dead code
**File:** `paper.py:932-945`  
**Fix:** Remove the `filled`/`pos_quantity` partial fill simulation — it's computed but never applied (the full position is always exited). Clean up the log message to remove the misleading partial-fill reference.

---

## Phase 4 — P3: Low-Priority Cleanup

- **`weather_markets.py:165`** — Delete `_STATION_BIAS = _STATION_BIAS_HIGH` alias (no callers).
- **`weather_markets.py:3049-3050` and `3204-3205`** — Remove duplicate `kelly = ...` line; keep only `fee_kel`.
- **`cron.py:328-349`** — Narrow the CB import except to `ImportError` only; let other exceptions propagate so real errors surface.
- **`calibration.py:207-223`** — Wrap the manual SQLite connection in a `with sqlite3.connect(...) as con:` context manager, consistent with the rest of the module.

---

## Phase 5 — Features (ranked by ROI)

### Feature 1 · Cross-market arbitrage auto-execution
**Files:** `cron.py`, minor addition to `consistency.py`  
**Approach:**
1. In `_cmd_cron_body`, after `markets` is fetched, call `find_violations(markets)`.
2. Filter to `guaranteed_edge > 0.05` (noise filter).
3. For each violation, look up the `buy_ticker` market in the fetched markets list and build an opportunity dict with `signal="ARBITRAGE"`, `adjusted_edge=v.guaranteed_edge`, `recommended_side="yes"`, and the minimum Kelly size (these are near-certainty trades — size conservatively at 2% bankroll regardless of Kelly).
4. Prepend to `strong_opps` so they're placed first.
5. Log arbitrage violations to a separate `data/arbitrage_log.jsonl` for tracking.

### Feature 2 · Intraday METAR same-day scanning (2 PM sweep)
**Files:** `cron.py`, `weather_markets.py`  
**Approach:**
1. Add a `_metar_sweep(markets, client)` function in `cron.py`.
2. Called only when UTC hour corresponds to after 2 PM local in any tracked city (check `_CITY_COORDS` timezones).
3. Filters `markets` to `days_out == 0` and `condition["type"] in ("above", "below")` (not "between").
4. For each, fetches METAR via the existing `_metar_lock_in` path and if `lock_prob >= 0.90` or `lock_prob <= 0.10` (near-certain), and market implied_prob differs by `>= 0.10`, create a HIGH-confidence signal.
5. These bypass the normal ensemble pipeline entirely — pure METAR-driven edge.

### Feature 3 · Dynamic edge threshold by market liquidity
**Files:** `weather_markets.py`  
**Approach:**
1. Add `_liquidity_edge_scale(volume: int, open_interest: int) -> float` that returns a multiplier `>= 1.0`:
   - `liq = volume + open_interest`
   - Returns `1.0` if `liq >= 500`, `1.5` if `liq <= 50`, linear interpolation between.
2. In `analyze_trade`, after `adjusted_edge` is computed, apply: `gated_edge = adjusted_edge / _liquidity_edge_scale(volume, oi)`.
3. Use `gated_edge` for the STRONG/MED/MIN threshold checks (not `adjusted_edge`). Keep `adjusted_edge` stored in the opp dict for display.

---

## Critical Files Modified

| File | Sections Changed |
|------|-----------------|
| `paper.py` | `settle_paper_trade`, `get_daily_pnl`, `get_current_streak`, `_score_ensemble_members`, `check_exit_targets`, 5× exposure functions |
| `weather_markets.py` | `load_learned_weights`, `_weights_from_mae`, `_NBM_CACHE`/`_ECMWF_CACHE`/`_CONSENSUS_CACHE`, `MIN_MARKET_PRICE`, obs noon gate, `_precip_clim_prior` |
| `calibration.py` | `_best_weights` (scipy), `calibrate_condition_weights` context manager |
| `cron.py` | arbitrage integration, `_metar_sweep`, CB import narrowing |
| `nws.py` | no change (noon gate lives in weather_markets.py) |
| `ml_bias.py` | pickle hash verification |
| `consistency.py` | no change (integration is in cron.py) |

## Execution Order

Implement in this sequence to avoid cascading breaks:
1. P0 fixes (paper.py financial safety) — these are independent
2. P0-3 + P0-5 (weather_markets.py) — independent
3. P1-1, P1-5 (weather_markets.py small fixes) — independent
4. P1-2 (calibration.py scipy) — independent
5. P1-3 (cron.py arbitrage) — depends on consistency.py being unchanged
6. P1-4 (obs noon gate) — independent
7. P2 fixes in order — all independent
8. P3 cleanup — last (cosmetic)
9. Features 1, 2, 3 — after all fixes are stable

## Verification

- Run `python main.py scan` and confirm no traceback
- Run `python -m pytest tests/ -x -q` — all tests must pass
- Manually verify: `python main.py today` shows correct settled_at timestamps
- Manually verify: `python main.py admin reset-loss` still works (touches daily limit path)
- Check calibration speed: `python main.py calibrate` should complete in <5s (down from potentially 30s+)
- After one cron run: inspect `data/cron.log` for arbitrage violation entries
