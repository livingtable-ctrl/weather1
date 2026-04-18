# Do After Graduation

> **Trigger:** 30+ settled trades in the predictions DB. Run `python main.py tracker` to check the count.
> Until then, none of these are urgent — the system is production-safe as-is.

---

## Priority 1 — Architecture (removes technical debt introduced during remediation)

### 1a. Extract `paths.py` to break `cron.py ↔ main.py` circular dependency

**Problem:** `cron.py` accesses `LOCK_PATH`, `KILL_SWITCH_PATH`, and `RUNNING_FLAG_PATH` via `sys.modules.get("main") or sys.modules["__main__"]` at runtime. This makes the dependency graph invisible to static analysis and is fragile.

**Fix:** Create `paths.py`:
```python
from pathlib import Path
LOCK_PATH = Path("data/.cron.lock")
KILL_SWITCH_PATH = Path("data/.kill_switch")
RUNNING_FLAG_PATH = Path("data/.cron_running")
```
Both `main.py` and `cron.py` import from `paths.py` directly. Remove `_main_module()`, `_lock_path()`, `_kill_switch_path()`, `_running_flag_path()` from `cron.py`. Remove the `# noqa: F401` re-export block in `main.py`.

---

### 1b. Wire `MAX_DRAWDOWN_FRACTION` through `BotConfig`

**Problem:** `paper.py` line ~106 reads `MAX_DRAWDOWN_FRACTION = float(os.getenv("DRAWDOWN_HALT_PCT", "0.20"))` directly, bypassing `BotConfig`. The value can silently diverge from `config.py`'s `drawdown_halt_pct`.

**Fix:** In `paper.py`, replace the `os.getenv` call with:
```python
from config import BotConfig as _BotConfig
MAX_DRAWDOWN_FRACTION = _BotConfig().drawdown_halt_pct
```
Or better: pass it in at startup. Then `drawdown_scaling_factor()` uses a single authoritative source.

---

### 1c. Split `weather_markets.py` (3,700 lines) into focused modules

Current file mixes forecast fetching, ensemble blending, edge calculation, market selection, and WebSocket price lookup. Suggested split:
- `forecast_fetch.py` — Open-Meteo, NWS, WeatherAPI HTTP calls
- `ensemble.py` — ensemble blending, model weighting, `get_ensemble_temps`
- `edge_calc.py` — `analyze_trade`, `edge_confidence`, `time_decay_edge`
- `weather_markets.py` — market selection, `get_weather_markets` (entry point only)

---

### 1d. Split `paper.py` (2,193 lines) into focused modules

- `ledger.py` — `get_balance`, `add_trade`, `settle_trade`, file I/O, checksums
- `sizing.py` — `kelly_bet_dollars`, `_dynamic_kelly_cap`, drawdown tiers
- `paper.py` — remaining orchestration, backup/encryption, streak logic

---

## Priority 2 — Security

### 2a. Timing-safe dashboard password comparison

**Problem:** `web_app.py` compares `DASHBOARD_PASSWORD` with plain `==`, which is a timing oracle on a local network.

**Fix:** Replace with `hmac.compare_digest`:
```python
import hmac
if not hmac.compare_digest(provided_password, DASHBOARD_PASSWORD):
    ...
```

---

## Priority 3 — Trading Logic (requires data — do after graduation)

### 3a. Empirical validation of `STRONG_EDGE` and `MIN_EDGE`

Once 30+ trades have settled, run `tracker.get_edge_decay_curve()` and plot actual win rate vs declared edge at entry. Adjust `STRONG_EDGE` (currently 0.30) and `MIN_EDGE` (currently 0.07) to match the empirical distribution.

### 3b. Per-station bias calibration

Check `tracker.get_calibration_by_city()` for systematic over/under-prediction by city. Cities with consistent bias should have their forecast adjusted before edge calculation.

### 3c. Blend weight review

Review `_model_weights()` in `weather_markets.py` against actual Brier scores by model from the tracker DB. The fallback weights are reasonable priors; replace with data-driven values once 30+ samples exist per model.

### 3d. `analyze_trade` refactor

The function is ~700 lines with deeply nested conditionals. Once the trading logic is empirically validated, break it into named sub-functions (`_score_temperature_market`, `_score_precip_market`, etc.) to make the signal flow auditable.

---

## Priority 4 — Testing

### 4a. Unit tests for `main.py` individual functions

Current coverage of `main.py` is mostly via smoke tests. Add unit tests for `cmd_watch`, `cmd_analyze`, `cmd_brief`, and the argparse dispatch.

### 4b. Ensemble blend math unit tests

`weather_markets.py`'s ensemble weighting math has integration-level tests but no unit tests for the weighting arithmetic itself. Add targeted tests for `_model_weights` and the weighted-average calculation in `get_ensemble_temps`.

---

## Grade Projection After All Items

| Area | Current | After |
|------|---------|-------|
| Architecture | C+ | B+ |
| Code Quality | B+ | A− |
| Risk Management | A− | A |
| Trading Logic | B | A− (data-dependent) |
| Testing | B− | B+ |
| Security | B | A− |
| **Overall** | **B** | **A−** |
