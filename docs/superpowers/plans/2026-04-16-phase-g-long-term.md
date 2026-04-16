# Phase G: Long-Term Features Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement five long-term improvement features: ML-based bias correction, cross-platform arbitrage scanner, A/B experiment framework, strategy P&L attribution, and Telegram alerting.

**Architecture:** Each feature is independent. ML bias correction adds a trained LightGBM model alongside the static bias table from Phase A. Cross-platform arbitrage requires a Polymarket API client. A/B framework extends the existing paper trade infrastructure. P&L attribution adds columns to the tracker DB. Telegram uses python-telegram-bot or httpx for simple webhook delivery.

**Prerequisites:**
- Phase A (bias correction foundation) before ML bias correction
- Phase D (per-city Brier) before P&L attribution
- 6+ months of settled trade data before ML bias correction is useful

**Tech Stack:** Python 3.12, scikit-learn or lightgbm, python-telegram-bot, httpx, pytest

---

## Task 1: ML-Based Bias Correction (LightGBM per city/season)

**Files:**
- Create: `ml_bias.py`
- Modify: `weather_markets.py` (use ML bias if model available)
- Create: `tests/test_ml_bias.py`

**Approach:** Train a LightGBM or sklearn `GradientBoostingRegressor` per city on features:
- `forecast_temp`: Raw model forecast
- `month`: Calendar month (1-12)
- `days_out`: Lead time in days
- `ensemble_spread_f`: Model spread (from Phase C)
- Target: `actual_cli_high - forecast_temp` (error to correct)

The model is trained on data from the tracker DB (`predictions` + `outcomes` tables). Retrained monthly. At prediction time, `apply_ml_bias(city, forecast_temp, month, days_out)` returns the corrected temperature.

**Prerequisite:** Need 6+ months of data (200+ settled predictions per city) for this to outperform the static bias table. Start collecting now; train in Phase G.

- [ ] **Step 1: Write failing tests**

Create `tests/test_ml_bias.py`:

```python
"""Tests for ML-based bias correction."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestMLBias:
    def test_train_bias_model_returns_dict(self, tmp_path, monkeypatch):
        """train_bias_model returns a dict with per-city models."""
        import tracker, ml_bias
        monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "predictions.db")
        monkeypatch.setattr(tracker, "_db_initialized", False)
        monkeypatch.setattr(ml_bias, "_MODEL_PATH", tmp_path / "bias_models.pkl")
        tracker.init_db()

        # Need at least some training data
        # With no data, should return empty dict or fail gracefully
        result = ml_bias.train_bias_model(min_samples=50)
        assert isinstance(result, dict)

    def test_apply_ml_bias_falls_back_when_no_model(self):
        """apply_ml_bias returns forecast unchanged if no trained model exists."""
        import ml_bias
        from unittest.mock import patch

        with patch.object(ml_bias, "_load_models", return_value={}):
            result = ml_bias.apply_ml_bias("NYC", 72.0, month=4, days_out=3)
        assert result == pytest.approx(72.0)

    def test_apply_ml_bias_adjusts_temperature(self, tmp_path, monkeypatch):
        """apply_ml_bias returns adjusted temp when model is available."""
        import ml_bias
        from unittest.mock import patch, MagicMock

        # Fake model that always predicts +2°F correction
        fake_model = MagicMock()
        fake_model.predict.return_value = [2.0]

        with patch.object(ml_bias, "_load_models", return_value={"NYC": fake_model}):
            result = ml_bias.apply_ml_bias("NYC", 70.0, month=4, days_out=3)

        # Corrected: 70.0 - 2.0 = 68.0 (subtract predicted error)
        assert result == pytest.approx(68.0, abs=0.1)
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd "C:/Users/thesa/claude kalshi"
python -m pytest tests/test_ml_bias.py -v
```

Expected: `ModuleNotFoundError: No module named 'ml_bias'`

- [ ] **Step 3: Implement `ml_bias.py`**

Create `ml_bias.py`:

```python
"""
ML-based bias correction — LightGBM per-city temperature error correction.
Requires 200+ settled predictions per city to outperform static bias table.
Train: python main.py train-bias
Use: apply_ml_bias() is called by analyze_trade() when a model exists.
"""
from __future__ import annotations

import logging
import pickle
from pathlib import Path

_log = logging.getLogger(__name__)
_MODEL_PATH = Path(__file__).parent / "data" / "bias_models.pkl"


def _build_features(forecast_temp: float, month: int, days_out: int, spread_f: float = 0.0) -> list:
    """Build feature vector for bias prediction."""
    return [forecast_temp, month, days_out, spread_f]


def _load_models() -> dict:
    """Load trained bias models from disk. Returns {} if not found."""
    if not _MODEL_PATH.exists():
        return {}
    try:
        with open(_MODEL_PATH, "rb") as f:
            return pickle.load(f)
    except Exception as exc:
        _log.debug("ml_bias: load failed: %s", exc)
        return {}


def train_bias_model(min_samples: int = 200) -> dict:
    """
    Train a bias correction model per city from tracker DB data.
    Saves models to data/bias_models.pkl.

    Returns dict of {city: model} for cities with enough data.
    """
    try:
        from sklearn.ensemble import GradientBoostingRegressor
    except ImportError:
        try:
            import lightgbm as lgb
        except ImportError:
            _log.warning("ml_bias: neither scikit-learn nor lightgbm installed. Run: pip install scikit-learn")
            return {}

    import tracker
    import sqlite3

    city_data: dict[str, list] = {}
    try:
        with tracker._conn() as con:
            rows = con.execute(
                """
                SELECT
                    p.city, p.our_prob,
                    CAST(strftime('%m', p.market_date) AS INTEGER) AS month,
                    CAST(julianday(p.market_date) - julianday(p.predicted_at) AS INTEGER) AS days_out,
                    o.settled_yes
                FROM predictions p
                JOIN outcomes o ON p.ticker = o.ticker
                WHERE p.city IS NOT NULL AND p.our_prob IS NOT NULL
                """
            ).fetchall()
    except Exception as exc:
        _log.warning("ml_bias: DB query failed: %s", exc)
        return {}

    for city, our_prob, month, days_out, settled_yes in rows:
        if city not in city_data:
            city_data[city] = []
        # Target: actual outcome - predicted probability (calibration error)
        actual = 1.0 if settled_yes else 0.0
        city_data[city].append({
            "our_prob": float(our_prob or 0),
            "month": int(month or 1),
            "days_out": max(0, int(days_out or 1)),
            "actual": actual,
        })

    models = {}
    for city, samples in city_data.items():
        if len(samples) < min_samples:
            _log.debug("ml_bias: %s has %d samples, need %d", city, len(samples), min_samples)
            continue

        X = [[s["our_prob"], s["month"], s["days_out"], 0.0] for s in samples]
        y = [s["actual"] - s["our_prob"] for s in samples]  # calibration error

        try:
            model = GradientBoostingRegressor(n_estimators=100, max_depth=3)
            model.fit(X, y)
            models[city] = model
            _log.info("ml_bias: trained model for %s on %d samples", city, len(samples))
        except Exception as exc:
            _log.warning("ml_bias: training failed for %s: %s", city, exc)

    if models:
        _MODEL_PATH.parent.mkdir(exist_ok=True)
        with open(_MODEL_PATH, "wb") as f:
            pickle.dump(models, f)
        _log.info("ml_bias: saved %d city models to %s", len(models), _MODEL_PATH)

    return models


def apply_ml_bias(
    city: str,
    forecast_temp: float,
    month: int,
    days_out: int,
    spread_f: float = 0.0,
) -> float:
    """
    Apply ML-based bias correction to a forecast temperature.

    Falls back to forecast_temp unchanged if no model exists for the city.
    """
    models = _load_models()
    model = models.get(city.upper())
    if model is None:
        return forecast_temp

    try:
        features = _build_features(forecast_temp, month, days_out, spread_f)
        correction = float(model.predict([features])[0])
        return forecast_temp - correction
    except Exception as exc:
        _log.debug("apply_ml_bias(%s): %s", city, exc)
        return forecast_temp
```

- [ ] **Step 4: Run tests to verify they pass**

```
python -m pytest tests/test_ml_bias.py -v
```

Expected: 3 tests PASSED

- [ ] **Step 5: Add `cmd_train_bias` to `main.py`**

```python
def cmd_train_bias() -> None:
    """Train ML bias correction models from tracker DB data."""
    from ml_bias import train_bias_model

    print("Training ML bias models (requires 200+ settled trades per city)...")
    models = train_bias_model(min_samples=200)
    if not models:
        print("Not enough data yet. Keep trading — retrain after 6 months.")
    else:
        print(f"Trained models for: {', '.join(sorted(models.keys()))}")
```

Wire: `"train-bias": lambda _a: cmd_train_bias()`

- [ ] **Step 6: Commit**

```bash
git add ml_bias.py tests/test_ml_bias.py main.py
git commit -m "feat(phase-g): add ML bias correction with GradientBoosting per city; py main.py train-bias"
```

---

## Task 2: Strategy P&L Attribution

**Files:**
- Modify: `tracker.py` (add `signal_source` column to predictions table)
- Modify: `main.py` (add `cmd_pnl_attribution`)
- Create: `tests/test_pnl_attribution.py`

**What it does:** When logging a trade, record which signal drove the decision (`ensemble`, `mos`, `metar_lockout`, `settlement_lag`, `gaussian`). Then query P&L broken down by signal source — reveals which signals are profitable.

- [ ] **Step 1: Write failing tests**

Create `tests/test_pnl_attribution.py`:

```python
"""Tests for strategy P&L attribution by signal source."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def tmp_tracker(tmp_path, monkeypatch):
    import tracker
    monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "predictions.db")
    monkeypatch.setattr(tracker, "_db_initialized", False)
    tracker.init_db()
    return tracker


class TestPnLAttribution:
    def test_log_prediction_accepts_signal_source(self, tmp_tracker):
        """log_prediction stores signal_source kwarg."""
        import sqlite3

        tmp_tracker.log_prediction(
            "TICKER-A", "NYC", date(2026, 4, 17),
            {"forecast_prob": 0.70, "market_prob": 0.50, "edge": 0.20, "condition": {}},
            signal_source="metar_lockout",
        )
        with sqlite3.connect(tmp_tracker.DB_PATH) as con:
            row = con.execute(
                "SELECT signal_source FROM predictions WHERE ticker='TICKER-A'"
            ).fetchone()
        assert row is not None
        assert row[0] == "metar_lockout"

    def test_get_pnl_by_signal_source_groups_correctly(self, tmp_tracker):
        """get_pnl_by_signal_source returns per-source stats."""
        for i in range(12):
            ticker = f"ENS-{i}"
            tmp_tracker.log_prediction(
                ticker, "NYC", date(2026, 4, i + 1),
                {"forecast_prob": 0.70, "market_prob": 0.50, "edge": 0.20, "condition": {}},
                signal_source="ensemble",
            )
            tmp_tracker.log_outcome(ticker, True)

        for i in range(8):
            ticker = f"MET-{i}"
            tmp_tracker.log_prediction(
                ticker, "NYC", date(2026, 4, i + 1),
                {"forecast_prob": 0.90, "market_prob": 0.50, "edge": 0.40, "condition": {}},
                signal_source="metar_lockout",
            )
            tmp_tracker.log_outcome(ticker, True)

        result = tmp_tracker.get_pnl_by_signal_source(min_samples=5)
        assert "ensemble" in result
        assert "metar_lockout" in result
        assert result["metar_lockout"]["n"] >= 8

    def test_get_pnl_by_signal_source_has_required_keys(self, tmp_tracker):
        """Each entry has brier, n, win_rate keys."""
        for i in range(12):
            ticker = f"T-{i}"
            tmp_tracker.log_prediction(
                ticker, "NYC", date(2026, 4, i + 1),
                {"forecast_prob": 0.65, "market_prob": 0.50, "edge": 0.15, "condition": {}},
                signal_source="mos",
            )
            tmp_tracker.log_outcome(ticker, i % 2 == 0)

        result = tmp_tracker.get_pnl_by_signal_source(min_samples=5)
        if "mos" in result:
            assert "brier" in result["mos"]
            assert "n" in result["mos"]
            assert "win_rate" in result["mos"]
```

- [ ] **Step 2: Run tests to verify they fail**

```
python -m pytest tests/test_pnl_attribution.py -v
```

Expected: `AttributeError: module 'tracker' has no attribute 'get_pnl_by_signal_source'`

- [ ] **Step 3: Add `signal_source` column via DB migration in `tracker.py`**

Find `_SCHEMA_VERSION` in `tracker.py` (currently `10`). Bump to `11` and add migration:

```python
_SCHEMA_VERSION = 11
```

In `_MIGRATIONS` dict, add:
```python
11: "ALTER TABLE predictions ADD COLUMN signal_source TEXT",
```

Update `log_prediction()` to accept and store `signal_source=None`:

In the UPDATE and INSERT paths:
```python
def log_prediction(
    ticker: str,
    city: str,
    market_date,
    analysis: dict,
    edge_calc_version: str | None = None,
    signal_source: str | None = None,  # ADD THIS
) -> None:
```

In the INSERT:
```python
# Add to INSERT column list and values
"signal_source": signal_source,
```

Add `get_pnl_by_signal_source()`:

```python
def get_pnl_by_signal_source(min_samples: int = 10) -> dict[str, dict]:
    """
    Compute Brier score and win rate grouped by signal_source.
    Reveals which signal drives the most profitable trades.
    """
    init_db()
    with _conn() as con:
        rows = con.execute(
            """
            SELECT
                COALESCE(p.signal_source, 'unknown') AS source,
                p.our_prob,
                o.settled_yes
            FROM predictions p
            JOIN outcomes o ON p.ticker = o.ticker
            WHERE p.our_prob IS NOT NULL
            """
        ).fetchall()

    groups: dict[str, list[tuple[float, bool]]] = {}
    for source, our_prob, settled_yes in rows:
        groups.setdefault(source, []).append((float(our_prob), bool(settled_yes)))

    result = {}
    for source, samples in groups.items():
        if len(samples) < min_samples:
            continue
        brier = sum((p - (1 if y else 0)) ** 2 for p, y in samples) / len(samples)
        wins = sum(1 for p, y in samples if (y and p > 0.5) or (not y and p <= 0.5))
        result[source] = {
            "brier": round(brier, 4),
            "n": len(samples),
            "win_rate": round(wins / len(samples), 3),
        }
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

```
python -m pytest tests/test_pnl_attribution.py -v
```

Expected: 3 tests PASSED

- [ ] **Step 5: Add `cmd_pnl_attribution` to `main.py`**

```python
def cmd_pnl_attribution() -> None:
    """Show P&L attribution by signal source."""
    from tracker import get_pnl_by_signal_source
    from colorama import Fore, Style

    data = get_pnl_by_signal_source(min_samples=5)
    if not data:
        print("Not enough data per signal source (need 5+ settled per source).")
        return

    print(f"\n{'Signal Source':<20} {'Brier':>8} {'Win%':>8} {'N':>6}")
    print("-" * 46)
    for src, d in sorted(data.items(), key=lambda x: x[1]["brier"]):
        brier = d["brier"]
        color = Fore.GREEN if brier < 0.15 else (Fore.YELLOW if brier < 0.22 else Fore.RED)
        print(f"{src:<20} {color}{brier:>8.4f}{Style.RESET_ALL} {d['win_rate']:>8.1%} {d['n']:>6}")
```

Wire: `"pnl-attribution": lambda _a: cmd_pnl_attribution()`

- [ ] **Step 6: Commit**

```bash
git add tracker.py tests/test_pnl_attribution.py main.py
git commit -m "feat(phase-g): add signal_source to predictions DB (migration v11); P&L attribution by signal"
```

---

## Task 3: Telegram Alerting

**Files:**
- Create: `telegram_alerts.py`
- Modify: `alerts.py` (call Telegram on anomaly/black swan)
- Modify: `main.py` (add `cmd_test_telegram`)
- Create: `tests/test_telegram_alerts.py`

**Setup:** User creates a bot via BotFather, gets a bot token + chat ID, sets env vars:
- `TELEGRAM_BOT_TOKEN=123456:ABC...`
- `TELEGRAM_CHAT_ID=-1001234567890`

- [ ] **Step 1: Write failing tests**

Create `tests/test_telegram_alerts.py`:

```python
"""Tests for Telegram alerting."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestTelegramAlerts:
    def test_send_message_calls_api(self):
        """send_telegram_message makes a POST to the Telegram API."""
        import telegram_alerts
        from unittest.mock import patch

        with patch.object(telegram_alerts, "_post_message", return_value=True) as mock_post:
            result = telegram_alerts.send_telegram_message("Test alert", "123:token", "456")
        mock_post.assert_called_once()
        assert result is True

    def test_send_message_no_op_without_config(self):
        """send_telegram_message returns False without token/chat_id."""
        import telegram_alerts
        result = telegram_alerts.send_telegram_message("Test", "", "")
        assert result is False

    def test_format_trade_notification(self):
        """format_trade_notification returns a string with ticker and outcome."""
        from telegram_alerts import format_trade_notification

        msg = format_trade_notification(
            ticker="KXHIGHNY-26APR17-T72",
            outcome="yes",
            edge=0.12,
            amount_dollars=15.50,
        )
        assert "KXHIGHNY-26APR17-T72" in msg
        assert "yes" in msg.lower() or "YES" in msg

    def test_format_anomaly_alert(self):
        """format_anomaly_alert includes the anomaly message."""
        from telegram_alerts import format_anomaly_alert

        msg = format_anomaly_alert("WIN RATE COLLAPSE: 20% in last 10 trades")
        assert "WIN RATE COLLAPSE" in msg
```

- [ ] **Step 2: Run tests to verify they fail**

```
python -m pytest tests/test_telegram_alerts.py -v
```

Expected: `ModuleNotFoundError: No module named 'telegram_alerts'`

- [ ] **Step 3: Implement `telegram_alerts.py`**

Create `telegram_alerts.py`:

```python
"""
Telegram alerting — send trade notifications and anomaly alerts to a Telegram chat.

Setup:
1. Create a bot via @BotFather on Telegram
2. Get your chat ID by messaging @userinfobot
3. Set env vars:
   TELEGRAM_BOT_TOKEN=123456:ABCdef...
   TELEGRAM_CHAT_ID=-1001234567890

Usage:
   from telegram_alerts import send_trade_alert, send_anomaly_alert
"""
from __future__ import annotations

import logging
import os

import requests

_log = logging.getLogger(__name__)
_API_BASE = "https://api.telegram.org/bot{token}/sendMessage"


def _post_message(token: str, chat_id: str, text: str) -> bool:
    """Make the actual Telegram API call."""
    url = _API_BASE.format(token=token)
    try:
        resp = requests.post(
            url,
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
        resp.raise_for_status()
        return True
    except Exception as exc:
        _log.debug("telegram: send failed: %s", exc)
        return False


def send_telegram_message(
    text: str,
    token: str | None = None,
    chat_id: str | None = None,
) -> bool:
    """
    Send a message to the configured Telegram chat.
    Returns True on success, False if not configured or on error.
    """
    token = token or os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return False
    return _post_message(token, chat_id, text)


def format_trade_notification(
    ticker: str,
    outcome: str,
    edge: float,
    amount_dollars: float,
) -> str:
    """Format a trade execution notification."""
    direction = "YES" if outcome == "yes" else "NO"
    return (
        f"🎯 <b>Trade Placed</b>\n"
        f"Ticker: <code>{ticker}</code>\n"
        f"Bet: <b>{direction}</b> @ ${amount_dollars:.2f}\n"
        f"Edge: {edge:.1%}"
    )


def format_anomaly_alert(anomaly_msg: str) -> str:
    """Format an anomaly detection alert."""
    return f"⚠️ <b>Anomaly Alert</b>\n{anomaly_msg}"


def format_black_swan_alert(reason: str) -> str:
    """Format a black swan emergency halt notification."""
    return f"🚨 <b>BLACK SWAN HALT</b>\n{reason}\n\nTrading suspended. Run <code>py main.py resume</code> to re-enable."


def send_trade_alert(ticker: str, outcome: str, edge: float, amount_dollars: float) -> None:
    """Send a trade execution alert to Telegram (fire-and-forget)."""
    msg = format_trade_notification(ticker, outcome, edge, amount_dollars)
    if not send_telegram_message(msg):
        _log.debug("telegram: trade alert not sent (not configured)")


def send_anomaly_alert(anomaly_msg: str) -> None:
    """Send an anomaly detection alert to Telegram."""
    msg = format_anomaly_alert(anomaly_msg)
    send_telegram_message(msg)


def send_black_swan_alert(reason: str) -> None:
    """Send a black swan halt notification to Telegram."""
    msg = format_black_swan_alert(reason)
    send_telegram_message(msg)
```

- [ ] **Step 4: Wire into `alerts.py`**

In `activate_black_swan_halt()`, after logging:
```python
# Notify via Telegram if configured
try:
    from telegram_alerts import send_black_swan_alert
    send_black_swan_alert(reason)
except Exception:
    pass
```

In `run_anomaly_check()`, after logging each anomaly:
```python
try:
    from telegram_alerts import send_anomaly_alert
    for msg in anomalies:
        send_anomaly_alert(msg)
except Exception:
    pass
```

- [ ] **Step 5: Add `cmd_test_telegram` to `main.py`**

```python
def cmd_test_telegram() -> None:
    """Send a test message to the configured Telegram chat."""
    from telegram_alerts import send_telegram_message

    ok = send_telegram_message("✅ Kalshi bot test message — alerting is working.")
    if ok:
        print("Telegram test message sent successfully.")
    else:
        print("Telegram not configured. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID env vars.")
```

Wire: `"test-telegram": lambda _a: cmd_test_telegram()`

- [ ] **Step 6: Run tests to verify they pass**

```
python -m pytest tests/test_telegram_alerts.py -v
```

Expected: 4 tests PASSED

- [ ] **Step 7: Run full test suite**

```
python -m pytest -x -q
```

Expected: all pass

- [ ] **Step 8: Commit**

```bash
git add telegram_alerts.py tests/test_telegram_alerts.py ml_bias.py tests/test_ml_bias.py alerts.py main.py tracker.py tests/test_pnl_attribution.py
git commit -m "feat(phase-g): long-term features — ML bias correction + P&L attribution + Telegram alerting"
```

---

## Cross-Platform Arbitrage Scanner (Stretch Goal)

This feature requires a Polymarket API client and is the most complex item in Phase G. It is documented here as a spec, not a full TDD plan — implement only after the other Phase G features are working.

**Approach:**
1. Fetch Kalshi YES prices for weather markets: `kalshi_client.get_markets(series_ticker="KXHIGH*")`
2. Fetch Polymarket prices for equivalent markets via their CLOB API
3. For each matching market: if `kalshi_yes_price + polymarket_no_price < 1.00 - fees`, there's an arbitrage
4. Execute both legs simultaneously (Kalshi + Polymarket APIs)
5. Risk: settlement definitions may differ slightly; settlement timing may differ

**Known issue:** Polymarket weather markets may not have perfect settlement definition parity with Kalshi. Always verify before executing. Start with paper/paper and confirm settlement parity over 10+ markets before going live/live.

**Files to create:**
- `polymarket_client.py` — fetches Polymarket CLOB prices
- `arb_scanner.py` — identifies cross-platform mispricings
- `tests/test_arb_scanner.py`
