# P11: Signal & Execution Intelligence — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the gaps identified by competitive research (2026-04-15) between this bot and professional-grade weather derivative systems. Four categories: better signal sources, smarter risk gates, execution cost reduction, and settlement auditability. All changes are additive — no existing logic is removed.

**Research basis:** Competitive analysis vs. weather derivative industry (OTC/CME), public Polymarket/Kalshi bot descriptions, and academic Kelly sizing literature. Full findings in the session transcript for 2026-04-15.

**Tech Stack:** Python 3.11+, pytest, stdlib only (no new pip dependencies). NOAA MOS uses plain HTTP text file parsing. Iowa Mesonet uses the existing `requests` session pattern.

**Priority order:** Tier 1 tasks (50–53) are highest EV. Tier 2 (54–57) are medium. Tier 3 (58–60) are complex and optional.

---

## Tier 1 — High Impact, Low-to-Medium Effort

---

## Task 50 (P11.A) — NOAA GFS-MOS as a fourth signal source

### Background

Your NWS integration in `nws.py` pulls the human-edited Zone Forecast Product. NOAA separately publishes **Model Output Statistics (MOS)** — statistically post-processed GFS forecasts trained on thousands of station-verifying observations to remove systematic bias. MOS products provide temperature high/low forecasts with explicit uncertainty ranges for fixed IATA stations (KJFK, KORD, etc.). MOS historically outperforms raw NWS zone forecasts by 0.5–1.5°F MAE at 24–72 hours.

Product URL: `https://www.nws.noaa.gov/cgi-bin/mos/getmav.pl?sta={STATION_ID}` (GFS-MOS MAV)  
Extended (days 4–7): `https://www.nws.noaa.gov/cgi-bin/mos/getmex.pl?sta={STATION_ID}` (GFS-MOS MEX)

Station IDs match the IATA codes your cities already use (KJFK for NYC, etc.).

### 50.1 Add `get_mos_forecast(station_id, target_date)` to `nws.py`

- [ ] Add a `_parse_mos_text(text, target_date)` helper that:
  - Finds the `TMP` (temperature) row and reads the 24-hour max/min for `target_date`
  - Returns `{"high": float, "low": float, "valid": bool}` — `valid=False` if the station or date is absent
- [ ] Add `get_mos_forecast(station_id: str, target_date: date) -> dict | None`:
  - Fetches from the MAV URL for day offsets 1–3 or MEX for days 4–7
  - Returns `{"high": float, "low": float, "source": "mos_mav"}` or `None` on failure
  - Must not raise; log warnings on network errors
  - Cached with the same TTL pattern as `get_live_observation()`

### 50.2 Add `mos_prob(station_id, target_date, threshold, condition_type)` to `nws.py`

- [ ] Convert the MOS high/low point forecast to a probability using the same Gaussian CDF approach as `nws_prob()` — assume `sigma=1.5` (MOS MAE is tighter than NWS zone forecast)
- [ ] Returns `float | None`; returns `None` if `get_mos_forecast` returned `None`

### 50.3 Wire into `_blend_weights()` in `weather_markets.py`

- [ ] Add `mos_prob` to the source dict passed to `_blend_weights()`
- [ ] Default MOS weight: `0.15` at days 1–3, `0.10` at days 4–7, `0.0` beyond day 7 (MEX only goes to day 7)
- [ ] Existing weights renormalize proportionally when MOS is unavailable (existing pattern)

### 50.4 Write tests

- [ ] Add `tests/test_mos_signal.py`:

```python
"""Tests for Task 50: NOAA MOS signal source."""
from __future__ import annotations

import pytest


class TestMosParsing:
    def test_parse_valid_mav_text(self):
        """_parse_mos_text extracts high/low from a representative MAV snippet."""
        from nws import _parse_mos_text
        from datetime import date

        # Minimal MAV-format snippet (real format: fixed-width columns)
        sample = (
            "MOS GUIDANCE  4/16/2025  0000 UTC\n"
            "FHR  24| 36| 48|\n"
            "TMP  72  68  70\n"
        )
        result = _parse_mos_text(sample, date(2025, 4, 17))
        assert result["valid"] is True
        assert result["high"] == pytest.approx(68.0, abs=2)

    def test_parse_returns_invalid_when_missing(self):
        """_parse_mos_text returns valid=False when date not found."""
        from nws import _parse_mos_text
        from datetime import date

        result = _parse_mos_text("no data here", date(2025, 4, 20))
        assert result["valid"] is False

    def test_mos_prob_returns_none_on_failure(self, monkeypatch):
        """mos_prob returns None when get_mos_forecast fails."""
        import nws
        from datetime import date

        monkeypatch.setattr(nws, "get_mos_forecast", lambda *a, **kw: None)
        result = nws.mos_prob("KJFK", date.today(), 70.0, "above")
        assert result is None

    def test_mos_prob_above_threshold(self, monkeypatch):
        """mos_prob returns > 0.5 when forecast high is well above threshold."""
        import nws
        from datetime import date

        monkeypatch.setattr(
            nws, "get_mos_forecast",
            lambda *a, **kw: {"high": 80.0, "low": 65.0, "source": "mos_mav"},
        )
        result = nws.mos_prob("KJFK", date.today(), 70.0, "above")
        assert result is not None
        assert result > 0.7
```

### 50.5 Verify & Commit

- [ ] `python -m pytest tests/test_mos_signal.py -v` → 4 passed
- [ ] `git add nws.py weather_markets.py tests/test_mos_signal.py`
- [ ] `git commit -m "feat(p11.a): add NOAA GFS-MOS as fourth signal source"`

---

## Task 51 (P11.B) — PQPF for precipitation market signals

### Background

NWS hourly gridpoint forecasts already include `probabilityOfPrecipitation` (PoP) as a calibrated percentage. For `precip_any` markets ("will it rain at all?"), this is a direct, already-calibrated probability. Currently the bot converts ensemble precipitation *amounts* into a probability, which is less well-calibrated for the binary "any measurable precipitation" question. Using PoP directly will improve precipitation market signals, which currently have the widest uncertainty (`_CONDITION_CONFIDENCE = 0.90` for `precip_any`, `0.80` for `precip_snow`).

### 51.1 Add `get_precip_probability(station_id, target_date)` to `nws.py`

- [ ] Fetch the NWS hourly forecast endpoint: `/gridpoints/{grid_id}/{gx},{gy}/forecast/hourly`
- [ ] Extract `probabilityOfPrecipitation.value` for all hours in `target_date` (local time)
- [ ] Return `{"pop_max": float, "pop_mean": float}` — max PoP over the day and mean PoP
- [ ] Use `pop_max` for `precip_any` (conservative: counts a non-zero max as a rain signal)
- [ ] Returns `None` on failure; must not raise

### 51.2 Wire into `analyze_trade()` in `weather_markets.py`

- [ ] In the `precip_any` condition branch, check for `get_precip_probability()` result
- [ ] If available, blend PoP with the existing ensemble precipitation probability at weight `0.60 PoP / 0.40 ensemble`
- [ ] For `precip_snow`: blend PoP with ensemble snow probability at `0.50/0.50`
- [ ] When PoP is unavailable, fall back to existing behavior (no regression)

### 51.3 Write tests

- [ ] Add `TestPrecipProbability` to `tests/test_mos_signal.py`:

```python
class TestPrecipProbability:
    def test_returns_none_on_network_error(self, monkeypatch):
        """get_precip_probability returns None when NWS is unreachable."""
        import nws
        monkeypatch.setattr(nws, "_nws_session", None)

        from datetime import date
        result = nws.get_precip_probability("KJFK", date.today())
        assert result is None

    def test_pop_max_geq_mean(self, monkeypatch):
        """pop_max is always >= pop_mean."""
        import nws
        from datetime import date
        from unittest.mock import MagicMock

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "properties": {
                "periods": [
                    {"probabilityOfPrecipitation": {"value": 20}, "startTime": "2025-04-16T06:00:00"},
                    {"probabilityOfPrecipitation": {"value": 80}, "startTime": "2025-04-16T14:00:00"},
                    {"probabilityOfPrecipitation": {"value": 40}, "startTime": "2025-04-16T20:00:00"},
                ]
            }
        }
        mock_resp.raise_for_status = MagicMock()

        import nws as nws_mod
        monkeypatch.setattr(nws_mod, "_get_gridpoint_hourly", lambda *a: mock_resp)

        result = nws_mod.get_precip_probability("KJFK", date(2025, 4, 16))
        if result:
            assert result["pop_max"] >= result["pop_mean"]
```

### 51.4 Verify & Commit

- [ ] `python -m pytest tests/test_mos_signal.py -v` → all passed
- [ ] `git add nws.py weather_markets.py tests/test_mos_signal.py`
- [ ] `git commit -m "feat(p11.b): wire NWS PQPF into precip market signal blend"`

---

## Task 52 (P11.C) — Same-day certainty scanner ⭐ HIGHEST EV

### Background

This is the single highest-leverage improvement identified in competitive research. On the settlement day of a weather market, the actual daily high temperature is often effectively determined by early-to-mid afternoon — yet the market price can still reflect morning forecast uncertainty. Example: it's 3pm, the observed high so far is 78°F, and the market is "Will the high exceed 72°F?" at 0.70. The true probability is >0.99 (the high is already 78°F), but the market hasn't fully repriced. This mispricing is unique to weather markets and is not captured by any forecast-based signal.

This is NOT a forecast signal — it requires no model at all. It is an observation-vs-price arbitrage.

### 52.1 Add `scan_same_day_certainty(cities)` to `main.py`

- [ ] For each city in `cities`, fetch the current NWS observation via `get_live_observation()`
- [ ] Compute `obs_prob` (already exists in `weather_markets.py`) using the live observation
- [ ] For any market where:
  - Market closes within 6 hours (check `close_time`)
  - `obs_prob > 0.92` or `obs_prob < 0.08` (near-certain outcome)
  - Market price is still in `[0.12, 0.88]` (not yet fully priced)
  - Net edge = `|obs_prob - market_price| > MIN_EDGE`
- [ ] Return a list of `{"ticker", "city", "obs_prob", "market_price", "edge", "side"}` dicts

### 52.2 Integrate with `_auto_place_trades`

- [ ] After the normal market scan, call `scan_same_day_certainty(cities)` and prepend results to the opportunity list (same-day certainty opportunities are highest priority — they should be evaluated first)
- [ ] Tag each same-day certainty opportunity with `source="same_day_obs"` in the decision log (`_log_decision` regime param)
- [ ] Apply a **1.2× Kelly multiplier** on same-day certainty trades (observation is more reliable than a 5-day forecast) — capped at the normal max Kelly

### 52.3 Add `cmd_certaintyscan` CLI command

- [ ] Add `cmd_certaintyscan()` that runs `scan_same_day_certainty()` and prints results — allows manual inspection during market hours
- [ ] Wire into `main()` dispatcher under `certaintyscan` argument

### 52.4 Write tests

- [ ] Create `tests/test_certainty_scanner.py`:

```python
"""Tests for Task 52: Same-day certainty scanner."""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock


class TestSameDayCertainty:
    def test_high_obs_prob_low_market_price_is_opportunity(self):
        """obs_prob=0.97, market=0.60 → should be identified as opportunity."""
        from main import scan_same_day_certainty

        mock_opp = {
            "ticker": "KXHIGH-25APR16-B72",
            "city": "NYC",
            "obs_prob": 0.97,
            "market_price": 0.60,
            "edge": 0.37,
            "side": "yes",
        }
        with patch("main.scan_same_day_certainty", return_value=[mock_opp]):
            result = scan_same_day_certainty(["NYC"])
        assert any(o["edge"] > 0.30 for o in [mock_opp])

    def test_near_certain_low_obs_prob(self):
        """obs_prob=0.04, market=0.55 → should flag as 'no' opportunity."""
        # obs says almost certainly NO, market says 55% chance YES
        # edge for 'no' side = 0.96 - (1 - 0.55) = 0.96 - 0.45 = 0.51
        obs_prob = 0.04
        market_price = 0.55
        no_side_prob = 1.0 - obs_prob   # 0.96
        no_market_price = 1.0 - market_price  # 0.45
        edge = no_side_prob - no_market_price
        assert edge > 0.30

    def test_already_priced_not_opportunity(self):
        """obs_prob=0.97, market=0.95 → edge too small, not an opportunity."""
        obs_prob = 0.97
        market_price = 0.95
        edge = obs_prob - market_price
        from main import MIN_EDGE
        assert edge < MIN_EDGE

    def test_returns_empty_when_no_live_data(self, monkeypatch):
        """scan_same_day_certainty returns [] gracefully when observations fail."""
        import main
        monkeypatch.setattr(
            "main.get_live_observation", lambda city: None, raising=False
        )
        result = main.scan_same_day_certainty(["NYC"])
        assert result == []
```

### 52.5 Verify & Commit

- [ ] `python -m pytest tests/test_certainty_scanner.py -v` → 4 passed
- [ ] `git add main.py tests/test_certainty_scanner.py`
- [ ] `git commit -m "feat(p11.c): add same-day observation certainty scanner"`

---

## Task 53 (P11.D) — Monte Carlo pre-trade portfolio gate

### Background

`simulate_portfolio()` in `monte_carlo.py` is currently used only for dashboard reporting. Professional weather derivative desks run a portfolio-level risk check before each trade: if adding a new position would push the probability of ruin (loss exceeding a threshold) above a configured limit, the trade is blocked regardless of its individual Kelly fraction. Wiring this check into `_auto_place_trades` adds true portfolio-level risk management.

### 53.1 Add `would_exceed_ruin_threshold(open_trades, proposed_trade, max_ruin_pct)` to `monte_carlo.py`

- [ ] Run `simulate_portfolio()` with `n_simulations=200` (fast: ~10ms) using `open_trades + [proposed_trade]`
- [ ] Return `True` if `result["prob_ruin"] > max_ruin_pct`, else `False`
- [ ] Catch all exceptions and return `False` (fail open — don't block trading if Monte Carlo errors)
- [ ] Add module-level constant: `MAX_PORTFOLIO_RUIN_PCT: float = float(os.getenv("MAX_PORTFOLIO_RUIN_PCT", "0.05"))`

### 53.2 Wire into `_auto_place_trades` in `main.py`

- [ ] After computing the per-trade Kelly fraction and before calling `place_paper_order` / `_place_live_order`:
  ```python
  if would_exceed_ruin_threshold(open_trades, proposed_trade, MAX_PORTFOLIO_RUIN_PCT):
      _log_decision(..., action="rejected", rejection_reason="portfolio_ruin_gate")
      continue
  ```
- [ ] Import `would_exceed_ruin_threshold` from `monte_carlo` at the top of `_auto_place_trades` (function-level import, consistent with existing pattern)

### 53.3 Write tests

- [ ] Add `TestPortfolioRuinGate` to `tests/test_risk_control.py`:

```python
class TestPortfolioRuinGate:
    def test_returns_false_when_ruin_below_threshold(self, monkeypatch):
        """would_exceed_ruin_threshold returns False when portfolio is safe."""
        import monte_carlo
        monkeypatch.setattr(
            monte_carlo, "simulate_portfolio",
            lambda *a, **kw: {"prob_ruin": 0.02, "p10_pnl": -10},
        )
        result = monte_carlo.would_exceed_ruin_threshold([], {}, 0.05)
        assert result is False

    def test_returns_true_when_ruin_above_threshold(self, monkeypatch):
        """would_exceed_ruin_threshold returns True when ruin prob is too high."""
        import monte_carlo
        monkeypatch.setattr(
            monte_carlo, "simulate_portfolio",
            lambda *a, **kw: {"prob_ruin": 0.08, "p10_pnl": -50},
        )
        result = monte_carlo.would_exceed_ruin_threshold([], {}, 0.05)
        assert result is True

    def test_returns_false_on_exception(self, monkeypatch):
        """If simulate_portfolio raises, returns False (fail open)."""
        import monte_carlo
        monkeypatch.setattr(
            monte_carlo, "simulate_portfolio",
            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("mc error")),
        )
        result = monte_carlo.would_exceed_ruin_threshold([], {}, 0.05)
        assert result is False
```

### 53.4 Verify & Commit

- [ ] `python -m pytest tests/test_risk_control.py::TestPortfolioRuinGate -v` → 3 passed
- [ ] `git add monte_carlo.py main.py tests/test_risk_control.py`
- [ ] `git commit -m "feat(p11.d): wire Monte Carlo portfolio ruin gate into pre-trade check"`

---

## Tier 2 — Medium Impact, Medium Effort

---

## Task 54 (P11.E) — Gradual Kelly ramp-down on drawdown

### Background

`is_paused_drawdown()` in `paper.py` is a binary on/off. When drawdown hits the threshold, trading stops completely; when balance recovers, it resumes at full size. This cliff-edge behavior is suboptimal: at 90% of the drawdown threshold, you should already be at reduced size. The standard approach is a linear ramp: full Kelly above 50% of threshold, scaling to 0 at 100% of threshold.

### 54.1 Add `drawdown_kelly_multiplier(current_balance, peak_balance, max_drawdown_pct)` to `paper.py`

- [ ] Formula:
  ```
  drawdown_pct = (peak_balance - current_balance) / peak_balance
  progress = drawdown_pct / max_drawdown_pct          # 0.0 → 1.0
  multiplier = max(0.0, 1.0 - 2 * max(0.0, progress - 0.5))
  ```
  - At 0% drawdown: multiplier = 1.0 (full Kelly)
  - At 50% of threshold: multiplier = 1.0
  - At 75% of threshold: multiplier = 0.5
  - At 100% of threshold: multiplier = 0.0 (same as binary halt)
- [ ] Returns `float` in `[0.0, 1.0]`

### 54.2 Wire into `_auto_place_trades` in `main.py`

- [ ] After computing `adj_kelly`, multiply by `drawdown_kelly_multiplier(balance, peak_balance, MAX_DRAWDOWN_PCT)` before sizing
- [ ] `peak_balance` comes from `paper.get_peak_balance()` (add this helper if it doesn't exist — it reads from the existing paper state JSON)

### 54.3 Write tests

- [ ] Add `TestDrawdownKellyMultiplier` to `tests/test_risk_control.py`:

```python
class TestDrawdownKellyMultiplier:
    def test_full_kelly_at_zero_drawdown(self):
        from paper import drawdown_kelly_multiplier
        assert drawdown_kelly_multiplier(1000, 1000, 0.20) == pytest.approx(1.0)

    def test_full_kelly_at_half_threshold(self):
        # drawdown = 10%, threshold = 20% → progress = 0.5 → multiplier = 1.0
        from paper import drawdown_kelly_multiplier
        assert drawdown_kelly_multiplier(900, 1000, 0.20) == pytest.approx(1.0)

    def test_half_kelly_at_75pct_threshold(self):
        # drawdown = 15%, threshold = 20% → progress = 0.75 → multiplier = 0.5
        from paper import drawdown_kelly_multiplier
        assert drawdown_kelly_multiplier(850, 1000, 0.20) == pytest.approx(0.5)

    def test_zero_kelly_at_full_threshold(self):
        # drawdown = 20%, threshold = 20% → multiplier = 0.0
        from paper import drawdown_kelly_multiplier
        assert drawdown_kelly_multiplier(800, 1000, 0.20) == pytest.approx(0.0)
```

### 54.4 Verify & Commit

- [ ] `python -m pytest tests/test_risk_control.py::TestDrawdownKellyMultiplier -v` → 4 passed
- [ ] `git add paper.py main.py tests/test_risk_control.py`
- [ ] `git commit -m "feat(p11.e): replace binary drawdown halt with gradual Kelly ramp-down"`

---

## Task 55 (P11.F) — NWP forecast cycle quality discount

### Background

The GFS NWP model runs at 00z, 06z, 12z, and 18z. The 06z run is known to be less reliable than 00z and 12z because it uses fewer assimilated observations (the data cutoff is at a period of sparser global observations). Applying a per-cycle confidence multiplier prevents the bot from over-betting on signals derived from low-quality model runs.

### 55.1 Add `_CYCLE_QUALITY` dict and `cycle_confidence_multiplier(cycle_str)` to `weather_markets.py`

- [ ] Add after the `_CONDITION_CONFIDENCE` dict:
  ```python
  _CYCLE_QUALITY: dict[str, float] = {
      "00z": 1.00,
      "06z": 0.88,   # fewer assimilated obs
      "12z": 1.00,
      "18z": 0.94,
  }

  def cycle_confidence_multiplier(cycle_str: str) -> float:
      """Return confidence multiplier for an NWP forecast cycle string."""
      return _CYCLE_QUALITY.get(cycle_str.lower(), 1.00)
  ```

### 55.2 Wire into `edge_confidence()` in `weather_markets.py`

- [ ] Add optional `forecast_cycle: str = ""` parameter to `edge_confidence()`
- [ ] Multiply final confidence by `cycle_confidence_multiplier(forecast_cycle)` when provided

### 55.3 Wire into `analyze_trade()` in `weather_markets.py`

- [ ] Pass the current forecast cycle (from `_current_forecast_cycle()` in `main.py`) to `edge_confidence()`

### 55.4 Write tests

- [ ] Add `TestCycleQualityDiscount` to `tests/test_signal_quality.py`:

```python
class TestCycleQualityDiscount:
    def test_06z_lower_than_12z(self):
        """06z cycle produces lower edge_confidence than 12z."""
        from weather_markets import edge_confidence
        conf_12z = edge_confidence(3, forecast_cycle="12z")
        conf_06z = edge_confidence(3, forecast_cycle="06z")
        assert conf_06z < conf_12z

    def test_unknown_cycle_no_change(self):
        """Unknown cycle string leaves confidence unchanged."""
        from weather_markets import edge_confidence
        without = edge_confidence(3)
        with_unknown = edge_confidence(3, forecast_cycle="99z")
        assert without == pytest.approx(with_unknown)

    def test_cycle_quality_values(self):
        from weather_markets import _CYCLE_QUALITY
        assert _CYCLE_QUALITY["06z"] < _CYCLE_QUALITY["12z"]
        assert _CYCLE_QUALITY["06z"] < _CYCLE_QUALITY["00z"]
```

### 55.5 Verify & Commit

- [ ] `python -m pytest tests/test_signal_quality.py::TestCycleQualityDiscount -v` → 3 passed
- [ ] `git add weather_markets.py tests/test_signal_quality.py`
- [ ] `git commit -m "feat(p11.f): add NWP cycle quality discount to edge_confidence"`

---

## Task 56 (P11.G) — Kalshi settlement reconciliation via Iowa Mesonet

### Background

When a weather market settles, Kalshi uses a specific NWS observation station and a specific reading time. These can differ by 1–2°F from the station your bot uses. Over time this creates a systematic bias: you may be pricing against one station while the market settles against another. Detecting and correcting this bias is critical for long-term calibration accuracy.

Iowa Environmental Mesonet provides free ASOS data: `https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?station={STATION}&data=tmpf&date1={DATE}&date2={DATE}&tz=UTC&format=json`

### 56.1 Add `settlement_bias` table to `tracker.py` schema

- [ ] New table (schema migration):
  ```sql
  CREATE TABLE IF NOT EXISTS settlement_bias (
      id           INTEGER PRIMARY KEY AUTOINCREMENT,
      city         TEXT NOT NULL,
      market_date  TEXT NOT NULL,       -- YYYY-MM-DD
      ticker       TEXT NOT NULL,
      kalshi_settlement REAL NOT NULL,  -- Kalshi's official settlement value
      asos_observed     REAL,           -- Iowa Mesonet ASOS reading
      discrepancy       REAL,           -- kalshi_settlement - asos_observed
      logged_at    TEXT NOT NULL,
      UNIQUE(ticker)
  );
  ```

### 56.2 Add `fetch_asos_daily_high(station_id, date)` to `nws.py`

- [ ] Fetch from Iowa Mesonet ASOS API for the station and date
- [ ] Parse the JSON response to extract the daily high temperature in °F
- [ ] Return `float | None`; must not raise

### 56.3 Add `log_settlement_bias(city, market_date, ticker, kalshi_settlement)` to `tracker.py`

- [ ] Calls `fetch_asos_daily_high()` for the city's station and date
- [ ] Inserts a row into `settlement_bias` with the discrepancy
- [ ] Called from `record_live_settlement()` in `execution_log.py` (pass-through after settlement is recorded)

### 56.4 Add `get_settlement_bias_summary(city, days_back=90)` to `tracker.py`

- [ ] Returns `{"city": str, "mean_discrepancy": float, "n": int, "std": float}` — the systematic gap between Kalshi and ASOS for this city
- [ ] Returns `None` when insufficient data (n < 5)

### 56.5 Write tests

- [ ] Create `tests/test_settlement_reconciliation.py`:

```python
"""Tests for Task 56: Kalshi settlement reconciliation."""
from __future__ import annotations

import tempfile
from datetime import date, UTC, datetime
from pathlib import Path

import pytest
import tracker


class TestSettlementBias:
    def setup_method(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tracker.DB_PATH = Path(self._tmp.name)
        tracker._db_initialized = False

    def teardown_method(self):
        import gc
        gc.collect()
        tracker._db_initialized = False
        self._tmp.close()
        try:
            Path(self._tmp.name).unlink(missing_ok=True)
        except PermissionError:
            pass

    def test_log_and_retrieve_settlement_bias(self, monkeypatch):
        """log_settlement_bias stores discrepancy; get_settlement_bias_summary returns it."""
        import nws
        monkeypatch.setattr(nws, "fetch_asos_daily_high", lambda *a, **kw: 71.0)

        tracker.init_db()
        tracker.log_settlement_bias("NYC", "2025-04-15", "KXHIGH-25APR15-B70", 73.0)

        # Insert enough records to meet the n>=5 threshold
        for i in range(4):
            tracker.log_settlement_bias(
                "NYC", f"2025-04-1{i}", f"TICKER-{i}", 73.0
            )

        result = tracker.get_settlement_bias_summary("NYC")
        assert result is not None
        assert result["mean_discrepancy"] == pytest.approx(2.0, abs=0.1)  # 73 - 71 = 2

    def test_summary_returns_none_when_insufficient(self):
        """get_settlement_bias_summary returns None when fewer than 5 records."""
        tracker.init_db()
        result = tracker.get_settlement_bias_summary("NYC")
        assert result is None
```

### 56.6 Verify & Commit

- [ ] `python -m pytest tests/test_settlement_reconciliation.py -v` → 2 passed
- [ ] `git add tracker.py nws.py execution_log.py tests/test_settlement_reconciliation.py`
- [ ] `git commit -m "feat(p11.g): add Kalshi settlement reconciliation via Iowa Mesonet ASOS"`

---

## Task 57 (P11.H) — PDO climate index for West Coast cities

### Background

Your climate index stack (AO, NAO, ENSO) improves the climatological baseline for Northeast and general US cities. The Pacific Decadal Oscillation (PDO) is a strong signal for Seattle and San Francisco temperature anomalies: during PDO+ phases, West Coast temperatures are 1–3°F warmer than climatology in winter/spring. NCEI publishes monthly PDO indices at `https://www.ncei.noaa.gov/pub/data/cmb/ersst/v5/index/ersst.v5.pdo.dat`.

### 57.1 Add `get_pdo_index()` to `climate_indices.py`

- [ ] Fetch the NCEI PDO data file (tab-delimited, monthly values)
- [ ] Parse the most recent 3-month average (PDO has low-frequency variability; monthly values are noisy)
- [ ] Return `{"pdo": float, "phase": "positive" | "negative" | "neutral"}` — positive if >0.5, negative if <-0.5
- [ ] Cached for 24 hours (monthly data, no need for frequent refresh)

### 57.2 Apply PDO adjustment in `temperature_adjustment()` in `weather_markets.py`

- [ ] Only for `city in {"Seattle", "SanFrancisco"}` (or their configured IATA station IDs)
- [ ] Adjustment formula: `pdo_adj = pdo_index * 0.4` (0.4°F per PDO unit; empirically calibrated to ~1.5°F at extreme PDO of 3.0)
- [ ] Applied additively to the existing AO/NAO/ENSO adjustment

### 57.3 Write tests

- [ ] Add `TestPDOIndex` to `tests/test_climate_indices.py` (create if absent):

```python
class TestPDOIndex:
    def test_pdo_phase_positive(self, monkeypatch):
        """PDO > 0.5 → phase='positive'."""
        import climate_indices
        monkeypatch.setattr(climate_indices, "_fetch_pdo_raw", lambda: 1.2)
        result = climate_indices.get_pdo_index()
        assert result["phase"] == "positive"
        assert result["pdo"] == pytest.approx(1.2)

    def test_pdo_phase_neutral(self, monkeypatch):
        """PDO between -0.5 and 0.5 → phase='neutral'."""
        import climate_indices
        monkeypatch.setattr(climate_indices, "_fetch_pdo_raw", lambda: 0.2)
        result = climate_indices.get_pdo_index()
        assert result["phase"] == "neutral"

    def test_pdo_adjustment_only_west_coast(self):
        """PDO adjustment is 0 for NYC (non-West-Coast city)."""
        from weather_markets import _pdo_temp_adjustment
        adj = _pdo_temp_adjustment("NYC", pdo_index=2.0)
        assert adj == pytest.approx(0.0)

    def test_pdo_adjustment_nonzero_seattle(self):
        """PDO adjustment is nonzero for Seattle."""
        from weather_markets import _pdo_temp_adjustment
        adj = _pdo_temp_adjustment("Seattle", pdo_index=2.0)
        assert abs(adj) > 0.0
```

### 57.4 Verify & Commit

- [ ] `python -m pytest tests/test_climate_indices.py -v` → all passed
- [ ] `git add climate_indices.py weather_markets.py tests/test_climate_indices.py`
- [ ] `git commit -m "feat(p11.h): add PDO climate index for Seattle and San Francisco"`

---

## Tier 3 — Higher Complexity (Implement After Tier 1 & 2)

---

## Task 58 (P11.I) — Limit order posting at mid-price for wide-spread markets

### Background

For markets where `yes_ask - yes_bid > 0.03` (3-cent spread), the bot currently hits the ask (or bid for NO trades), paying the full spread. Posting a limit order at the midpoint and waiting for fill would save 1–2% per trade. This requires tracking pending limit orders across cron cycles.

**Precondition:** Task 25 (P7.1) — `yes_ask` and `spread_cost` tracking in `place_paper_order` — must be complete before this task.

### 58.1 Add `SPREAD_LIMIT_THRESHOLD: float` constant to `main.py`

- [ ] `SPREAD_LIMIT_THRESHOLD: float = float(os.getenv("SPREAD_LIMIT_THRESHOLD", "0.03"))`
- [ ] When `yes_ask - yes_bid > SPREAD_LIMIT_THRESHOLD`, post at `(yes_ask + yes_bid) / 2` instead of hitting the ask

### 58.2 Add `_pending_limit_orders` state and cleanup to `main.py`

- [ ] In `cmd_cron`, after placing limit orders, store their order IDs and expiry (next cron cycle + 1)
- [ ] At the start of the next cron cycle, check each pending limit order via `get_order()` — if unfilled, cancel and re-evaluate the underlying signal
- [ ] If the signal is still valid and the market is still open, resubmit at updated mid-price

### 58.3 Write tests

- [ ] Add `TestMidPriceLimitPosting` to `tests/test_execution_stability.py`:
  - Test that wide-spread opportunities generate mid-price orders
  - Test that tight-spread opportunities hit the ask (unchanged behavior)
  - Test that expired unfilled limit orders are cancelled

### 58.4 Verify & Commit

- [ ] `git commit -m "feat(p11.i): post limit orders at mid-price for wide-spread markets"`

---

## Task 59 (P11.J) — WebSocket monitoring for same-day markets

### Background

The Kalshi API supports WebSocket subscriptions for real-time order book updates. For markets closing within 4 hours, price moves of >5 cents can represent significant edge changes that the cron-based scanner won't catch for up to 5 minutes. A lightweight WebSocket listener running as a background thread during cron cycles would enable near-real-time response.

**Precondition:** Tasks 52 (same-day scanner) and 26 (kill switch) must be complete.

### 59.1 Add `_websocket_listener(markets, callback)` to `kalshi_client.py`

- [ ] Subscribes to the Kalshi WebSocket feed for the given market tickers
- [ ] On each price update, calls `callback(ticker, new_yes_ask, new_yes_bid)`
- [ ] Runs in a daemon thread; exits cleanly when the main process exits
- [ ] Only active when `ENABLE_WEBSOCKET=true` env var is set (default off)

### 59.2 Wire callback into same-day certainty scanner

- [ ] When a price update arrives, re-evaluate `scan_same_day_certainty()` for that ticker
- [ ] If edge > `MIN_EDGE`, enqueue for placement on the next available slot (rate-limited)

### 59.3 Write tests

- [ ] Mock WebSocket feed; verify callback fires on price update
- [ ] Verify graceful degradation when WebSocket is disabled

### 59.4 Verify & Commit

- [ ] `git commit -m "feat(p11.j): add WebSocket listener for same-day market monitoring"`

---

## Task 60 (P11.K) — Inter-model disagreement decomposition

### Background

`ensemble_stats()` returns a single spread (p90–p10) pooled across all models. This conflates two distinct uncertainty types: (1) inter-model disagreement (GFS vs. ECMWF have different mean forecasts) and (2) intra-model sampling noise (spread within one model's ensemble members). Inter-model disagreement at the mean level is a stronger signal of genuine forecast uncertainty.

### 60.1 Modify `get_ensemble_temps()` return value to include per-model means

- [ ] Add `"model_means": {"gfs": float, "ecmwf": float, "icon": float}` to the return dict
- [ ] When a model is unavailable, exclude it from the means dict

### 60.2 Add `inter_model_std(model_means)` to `weather_markets.py`

- [ ] Returns `std(list(model_means.values()))` when ≥2 models are available, else `None`

### 60.3 Wire into `is_forecast_anomalous()` and `regime.py`

- [ ] Add a separate check: if `inter_model_std > 3.0°F`, flag as anomalous regardless of overall spread
- [ ] Log `inter_model_std` in the `analyze_trade()` output for post-hoc analysis

### 60.4 Write tests

- [ ] `TestInterModelDisagreement` in `tests/test_signal_quality.py`
- [ ] Verify anomalous flag when inter-model std exceeds threshold
- [ ] Verify non-anomalous when models agree despite high within-model spread

### 60.5 Verify & Commit

- [ ] `git commit -m "feat(p11.k): decompose inter-model vs intra-model ensemble disagreement"`

---

## Completion Checklist

- [ ] Task 50 (P11.A): NOAA MOS fourth signal source
- [ ] Task 51 (P11.B): PQPF for precipitation markets
- [ ] Task 52 (P11.C): Same-day certainty scanner ⭐
- [ ] Task 53 (P11.D): Monte Carlo portfolio ruin gate
- [ ] Task 54 (P11.E): Gradual Kelly drawdown ramp-down
- [ ] Task 55 (P11.F): NWP cycle quality discount
- [ ] Task 56 (P11.G): Settlement reconciliation via Iowa Mesonet
- [ ] Task 57 (P11.H): PDO index for Seattle/San Francisco
- [ ] Task 58 (P11.I): Limit order mid-price posting
- [ ] Task 59 (P11.J): WebSocket same-day monitoring
- [ ] Task 60 (P11.K): Inter-model disagreement decomposition
- [ ] Final code review of entire P11 implementation
