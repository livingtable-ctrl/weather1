# Phase D: Monitoring & Settlement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add three monitoring improvements: METAR settlement lag monitoring loop (second high-win-rate strategy), per-city/season Brier score segmentation in the tracker, and a reliability diagram on the Flask dashboard.

**Architecture:** Settlement lag runs as a standalone monitoring script (`settlement_monitor.py`) triggered separately from the cron cycle — it polls METAR after 5 PM and updates market signals. Per-city Brier adds a new DB query to `tracker.py`. Reliability diagram adds a new Flask API endpoint and Chart.js visualization.

**Prerequisites:** Phase A (METAR module) must be done first. Phase D uses `metar.fetch_metar()`.

**Tech Stack:** Python 3.12, SQLite, Flask, Chart.js (already in dashboard), pytest

---

## Task 1: Per-City Per-Season Brier Score Segmentation

**Files:**
- Modify: `tracker.py` (add `get_brier_by_city_season()`)
- Modify: `main.py` (add `cmd_city_performance` CLI command)
- Create: `tests/test_city_season_brier.py`

**Why:** The global Brier score hides where the bot is actually profitable. NYC in summer may have different edge than Chicago in winter. This segmentation reveals which city-season combinations have true edge — and which to avoid.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_city_season_brier.py`:

```python
"""Tests for per-city per-season Brier score segmentation."""
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


def _log_settle(t, ticker, city, market_date, our_prob, settled_yes):
    t.log_prediction(
        ticker, city, market_date,
        {"forecast_prob": our_prob, "market_prob": 0.5, "edge": our_prob - 0.5,
         "condition": {"type": "above", "threshold": 70}},
    )
    t.log_outcome(ticker, settled_yes)


class TestGetBrierByCitySeason:
    def test_empty_returns_empty_dict(self, tmp_tracker):
        result = tmp_tracker.get_brier_by_city_season()
        assert result == {}

    def test_groups_by_city(self, tmp_tracker):
        """Predictions for NYC and MIA appear in separate keys."""
        for i in range(12):
            _log_settle(tmp_tracker, f"NYC-{i}", "NYC", date(2026, 4, i + 1), 0.70, True)
        for i in range(12):
            _log_settle(tmp_tracker, f"MIA-{i}", "MIA", date(2026, 4, i + 1), 0.65, False)

        result = tmp_tracker.get_brier_by_city_season(min_samples=10)
        assert "NYC" in result
        assert "MIA" in result

    def test_groups_by_season(self, tmp_tracker):
        """Spring (Apr) and Summer (Jul) appear in separate season keys."""
        # Spring (month 4)
        for i in range(12):
            _log_settle(tmp_tracker, f"NYC-SPR-{i}", "NYC", date(2026, 4, i + 1), 0.70, True)
        # Summer (month 7)
        for i in range(12):
            _log_settle(tmp_tracker, f"NYC-SUM-{i}", "NYC", date(2026, 7, i + 1), 0.65, False)

        result = tmp_tracker.get_brier_by_city_season(min_samples=10)
        # Should have NYC entries for at least 2 different seasons
        nyc_seasons = {k for k in result if k.startswith("NYC_")}
        assert len(nyc_seasons) >= 2

    def test_result_has_brier_and_n(self, tmp_tracker):
        """Each entry has 'brier' and 'n' keys."""
        for i in range(12):
            _log_settle(tmp_tracker, f"TK-{i}", "NYC", date(2026, 4, i + 1), 0.70, True)

        result = tmp_tracker.get_brier_by_city_season(min_samples=10)
        assert "NYC" in result or any("NYC" in k for k in result)
        for entry in result.values():
            assert "brier" in entry
            assert "n" in entry

    def test_min_samples_filters_out_sparse(self, tmp_tracker):
        """Cities with fewer than min_samples predictions are excluded."""
        for i in range(5):
            _log_settle(tmp_tracker, f"SPARSE-{i}", "CHI", date(2026, 4, i + 1), 0.70, True)

        result = tmp_tracker.get_brier_by_city_season(min_samples=10)
        assert not any("CHI" in k for k in result)
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd "C:/Users/thesa/claude kalshi"
python -m pytest tests/test_city_season_brier.py -v
```

Expected: `AttributeError: module 'tracker' has no attribute 'get_brier_by_city_season'`

- [ ] **Step 3: Add `get_brier_by_city_season()` to `tracker.py`**

Add after `get_brier_by_version()`:

```python
def get_brier_by_city_season(min_samples: int = 10) -> dict[str, dict]:
    """
    Compute Brier score grouped by city AND season.

    Key format: "{CITY}_{SEASON}" where SEASON is Winter/Spring/Summer/Fall.
    Returns dict: {"NYC_Spring": {"brier": 0.12, "n": 45, "win_rate": 0.68}, ...}

    Only includes groups with at least min_samples settled predictions.
    """
    init_db()
    _SEASON_MAP = {
        1: "Winter", 2: "Winter",  # Dec is in season by month
        3: "Spring", 4: "Spring", 5: "Spring",
        6: "Summer", 7: "Summer", 8: "Summer",
        9: "Fall", 10: "Fall", 11: "Fall",
        12: "Winter",
    }
    with _conn() as con:
        rows = con.execute(
            """
            SELECT
                p.city,
                CAST(strftime('%m', p.market_date) AS INTEGER) AS month,
                p.our_prob,
                o.settled_yes
            FROM predictions p
            JOIN outcomes o ON p.ticker = o.ticker
            WHERE p.our_prob IS NOT NULL AND p.city IS NOT NULL
            """
        ).fetchall()

    # Group by city + season
    groups: dict[str, list[tuple[float, bool]]] = {}
    for city, month, our_prob, settled_yes in rows:
        season = _SEASON_MAP.get(month, "Unknown")
        key = f"{city}_{season}"
        groups.setdefault(key, []).append((float(our_prob), bool(settled_yes)))

    result = {}
    for key, samples in groups.items():
        if len(samples) < min_samples:
            continue
        brier = sum((p - (1 if y else 0)) ** 2 for p, y in samples) / len(samples)
        wins = sum(1 for p, y in samples if y and p > 0.5) + sum(1 for p, y in samples if not y and p <= 0.5)
        result[key] = {
            "brier": round(brier, 4),
            "n": len(samples),
            "win_rate": round(wins / len(samples), 3),
        }

    return result
```

- [ ] **Step 4: Add `cmd_city_performance()` to `main.py`**

```python
def cmd_city_performance() -> None:
    """Show Brier score and win rate broken down by city and season."""
    from tracker import get_brier_by_city_season
    from colorama import Fore, Style

    data = get_brier_by_city_season(min_samples=10)
    if not data:
        print("No per-city/season data yet (need 10+ settled predictions per segment).")
        return

    print(f"\n{'City+Season':<20} {'Brier':>8} {'Win%':>8} {'N':>6}")
    print("-" * 46)
    for key, d in sorted(data.items(), key=lambda x: x[1]["brier"]):
        brier = d["brier"]
        color = Fore.GREEN if brier < 0.15 else (Fore.YELLOW if brier < 0.22 else Fore.RED)
        print(f"{key:<20} {color}{brier:>8.4f}{Style.RESET_ALL} {d['win_rate']:>8.1%} {d['n']:>6}")
```

Wire into dispatch:
```python
"city-performance": lambda _a: cmd_city_performance(),
"city-perf": lambda _a: cmd_city_performance(),
```

- [ ] **Step 5: Run tests to verify they pass**

```
python -m pytest tests/test_city_season_brier.py -v
```

Expected: 5 tests PASSED

- [ ] **Step 6: Commit**

```bash
git add tracker.py main.py tests/test_city_season_brier.py
git commit -m "feat(monitoring): add per-city/season Brier segmentation; py main.py city-performance"
```

---

## Task 2: Reliability Diagram in Flask Dashboard

**Files:**
- Modify: `web_app.py` (add `/api/reliability` endpoint)
- Modify: `templates/analytics.html` (add reliability diagram chart)
- Create: `tests/test_reliability_diagram.py`

**What it shows:** Forecast probability bins (0-10%, 10-20%, ..., 90-100%) on X-axis vs. observed win rate in each bin on Y-axis. A perfectly calibrated model lies on the diagonal. Points above the diagonal = under-confident; below = over-confident.

The reliability data comes from the existing `predictions` + `outcomes` tables.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_reliability_diagram.py`:

```python
"""Tests for reliability diagram API endpoint."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def client(tmp_path, monkeypatch):
    import tracker, web_app
    monkeypatch.setattr(tracker, "DB_PATH", tmp_path / "predictions.db")
    monkeypatch.setattr(tracker, "_db_initialized", False)
    tracker.init_db()
    app = web_app.app
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


class TestReliabilityEndpoint:
    def test_endpoint_exists(self, client):
        """GET /api/reliability returns 200."""
        resp = client.get("/api/reliability")
        assert resp.status_code == 200

    def test_returns_json_with_bins(self, client):
        """Response has 'bins' list."""
        resp = client.get("/api/reliability")
        data = json.loads(resp.data)
        assert "bins" in data
        assert isinstance(data["bins"], list)

    def test_empty_data_returns_empty_bins(self, client):
        """No predictions → empty bins list."""
        resp = client.get("/api/reliability")
        data = json.loads(resp.data)
        # Either empty list or bins with n=0
        assert all(b.get("n", 0) == 0 for b in data["bins"]) or len(data["bins"]) == 0

    def test_bins_have_required_fields(self, client):
        """Each bin has prob_low, prob_high, observed_rate, n fields."""
        # Seed some data
        import tracker
        from datetime import date
        for i in range(5):
            ticker = f"T{i}"
            tracker.log_prediction(
                ticker, "NYC", date(2026, 4, i + 1),
                {"forecast_prob": 0.65, "market_prob": 0.5, "edge": 0.15, "condition": {}},
            )
            tracker.log_outcome(ticker, True)

        resp = client.get("/api/reliability")
        data = json.loads(resp.data)
        for b in data["bins"]:
            if b.get("n", 0) > 0:
                assert "prob_low" in b
                assert "prob_high" in b
                assert "observed_rate" in b
                assert "n" in b
```

- [ ] **Step 2: Run tests to verify they fail**

```
python -m pytest tests/test_reliability_diagram.py -v
```

Expected: test_endpoint_exists fails with 404

- [ ] **Step 3: Add `/api/reliability` endpoint to `web_app.py`**

In `web_app.py`, add:

```python
@app.route("/api/reliability")
def api_reliability():
    """
    Return reliability diagram data: observed win rate per probability bin.
    Bins: [0-10%, 10-20%, ..., 90-100%].
    """
    try:
        import tracker
        with tracker._conn() as con:
            rows = con.execute(
                """
                SELECT p.our_prob, o.settled_yes
                FROM predictions p
                JOIN outcomes o ON p.ticker = o.ticker
                WHERE p.our_prob IS NOT NULL
                """
            ).fetchall()
    except Exception as e:
        return jsonify({"error": str(e), "bins": []})

    # Build 10 bins: [0,0.1), [0.1,0.2), ..., [0.9,1.0]
    bin_edges = [i / 10 for i in range(11)]
    bins = []
    for i in range(10):
        low, high = bin_edges[i], bin_edges[i + 1]
        bucket = [(p, y) for p, y in rows if low <= p < high]
        if i == 9:  # include p=1.0 in last bin
            bucket = [(p, y) for p, y in rows if low <= p <= high]
        n = len(bucket)
        observed = sum(1 for _, y in bucket if y) / n if n > 0 else None
        bins.append({
            "prob_low": low,
            "prob_high": high,
            "prob_mid": (low + high) / 2,
            "observed_rate": round(observed, 3) if observed is not None else None,
            "n": n,
        })

    return jsonify({"bins": bins, "total": len(rows)})
```

- [ ] **Step 4: Add reliability diagram to `templates/analytics.html`**

Find the analytics template. Add a new section after the Brier score display:

```html
<!-- Reliability Diagram -->
<div class="card mb-4">
  <div class="card-header">Calibration Reliability Diagram</div>
  <div class="card-body">
    <p class="text-muted small">Points on the diagonal = perfectly calibrated. Above diagonal = under-confident; below = over-confident.</p>
    <canvas id="reliabilityChart" height="300"></canvas>
  </div>
</div>

<script>
fetch('/api/reliability')
  .then(r => r.json())
  .then(data => {
    const bins = data.bins.filter(b => b.n > 0);
    const labels = bins.map(b => `${Math.round(b.prob_mid * 100)}%`);
    const observed = bins.map(b => b.observed_rate !== null ? b.observed_rate : null);
    const predicted = bins.map(b => b.prob_mid);

    new Chart(document.getElementById('reliabilityChart'), {
      type: 'line',
      data: {
        labels: labels,
        datasets: [
          {
            label: 'Observed Win Rate',
            data: observed,
            borderColor: 'rgb(54, 162, 235)',
            backgroundColor: 'rgba(54, 162, 235, 0.1)',
            fill: true,
            tension: 0.1,
          },
          {
            label: 'Perfect Calibration',
            data: predicted,
            borderColor: 'rgba(200, 200, 200, 0.8)',
            borderDash: [5, 5],
            pointRadius: 0,
          }
        ]
      },
      options: {
        scales: {
          y: { min: 0, max: 1, title: { display: true, text: 'Observed Rate' } },
          x: { title: { display: true, text: 'Forecast Probability' } }
        }
      }
    });
  });
</script>
```

- [ ] **Step 5: Run tests to verify they pass**

```
python -m pytest tests/test_reliability_diagram.py -v
```

Expected: 4 tests PASSED

- [ ] **Step 6: Commit**

```bash
git add web_app.py templates/analytics.html tests/test_reliability_diagram.py
git commit -m "feat(monitoring): add reliability diagram — /api/reliability endpoint + Chart.js visualization"
```

---

## Task 3: METAR Settlement Lag Monitoring

**Files:**
- Create: `settlement_monitor.py`
- Modify: `main.py` (add `cmd_settlement_monitor` CLI command)
- Create: `tests/test_settlement_monitor.py`

**Strategy:** After 5 PM local time, METAR/DSM preliminary readings often confirm the day's final high temperature before the official NWS CLI report. Markets that haven't updated to reflect the known outcome can be traded at very favorable prices.

**Implementation:** `settlement_monitor.py` runs a loop from 5 PM to 7 PM local time for each active city, checking METAR every 5 minutes. When METAR confirms an outcome (using `metar.check_metar_lockout()` with tighter margin), it writes a signal to `data/settlement_signals.json`. The cron loop picks these up on next cycle.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_settlement_monitor.py`:

```python
"""Tests for METAR settlement lag monitoring."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestBuildSettlementSignal:
    def test_signal_structure(self):
        """build_settlement_signal returns dict with required keys."""
        from settlement_monitor import build_settlement_signal

        signal = build_settlement_signal(
            ticker="KXHIGHNY-26APR17-T72",
            city="NYC",
            outcome="yes",
            confidence=0.92,
            current_temp_f=80.0,
            threshold_f=72.0,
        )

        assert signal["ticker"] == "KXHIGHNY-26APR17-T72"
        assert signal["city"] == "NYC"
        assert signal["outcome"] == "yes"
        assert signal["confidence"] == 0.92
        assert "created_at" in signal
        assert signal["source"] == "metar_settlement_lag"

    def test_write_settlement_signals_creates_file(self, tmp_path, monkeypatch):
        """write_settlement_signals writes JSON to signals file."""
        import settlement_monitor
        signals_path = tmp_path / "settlement_signals.json"
        monkeypatch.setattr(settlement_monitor, "_SIGNALS_PATH", signals_path)

        from settlement_monitor import write_settlement_signals, build_settlement_signal
        signal = build_settlement_signal("TICKER", "NYC", "yes", 0.92, 80.0, 72.0)
        write_settlement_signals([signal])

        assert signals_path.exists()
        data = json.loads(signals_path.read_text())
        assert len(data["signals"]) == 1
        assert data["signals"][0]["ticker"] == "TICKER"

    def test_read_settlement_signals_empty_on_no_file(self, tmp_path, monkeypatch):
        """read_settlement_signals returns [] when file does not exist."""
        import settlement_monitor
        monkeypatch.setattr(settlement_monitor, "_SIGNALS_PATH", tmp_path / "nonexistent.json")

        from settlement_monitor import read_settlement_signals
        assert read_settlement_signals() == []

    def test_signals_expire_after_window(self, tmp_path, monkeypatch):
        """Signals older than max_age_minutes are filtered out."""
        import settlement_monitor
        from datetime import timedelta
        signals_path = tmp_path / "settlement_signals.json"
        monkeypatch.setattr(settlement_monitor, "_SIGNALS_PATH", signals_path)

        # Write a signal with an old timestamp
        old_time = (datetime.now(timezone.utc) - timedelta(minutes=90)).isoformat()
        signals_path.write_text(json.dumps({
            "signals": [{"ticker": "OLD", "created_at": old_time, "outcome": "yes"}]
        }))

        from settlement_monitor import read_settlement_signals
        result = read_settlement_signals(max_age_minutes=60)
        assert all(s["ticker"] != "OLD" for s in result)
```

- [ ] **Step 2: Run tests to verify they fail**

```
python -m pytest tests/test_settlement_monitor.py -v
```

Expected: `ModuleNotFoundError: No module named 'settlement_monitor'`

- [ ] **Step 3: Implement `settlement_monitor.py`**

Create `settlement_monitor.py`:

```python
"""
METAR Settlement Lag Monitor — P(D: Settlement & Monitoring).

Runs from 5 PM to 7 PM local time for each city, checking METAR every 5 minutes.
When METAR confirms the day's high temp outcome, writes a settlement signal.
The main cron loop picks up these signals on next cycle.

Run: python main.py settlement-monitor
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

_log = logging.getLogger(__name__)

_SIGNALS_PATH = Path(__file__).parent / "data" / "settlement_signals.json"
_SIGNALS_PATH.parent.mkdir(exist_ok=True)

# Cities and their METAR stations + timezones
_MONITOR_CITIES = {
    "NYC": {"station": "KNYC", "tz": "America/New_York"},
    "MIA": {"station": "KMIA", "tz": "America/New_York"},
    "CHI": {"station": "KORD", "tz": "America/Chicago"},
    "LAX": {"station": "KLAX", "tz": "America/Los_Angeles"},
    "DAL": {"station": "KDFW", "tz": "America/Chicago"},
}

# Settlement lag monitoring window: 5 PM – 7 PM local
_MONITOR_START_HOUR = 17
_MONITOR_END_HOUR = 19
# Tighter margin for settlement lag (1°F vs 3°F for day-trade METAR)
_SETTLEMENT_MARGIN_F = 1.0
_POLL_INTERVAL_SECONDS = 300  # 5 minutes


def build_settlement_signal(
    ticker: str,
    city: str,
    outcome: str,
    confidence: float,
    current_temp_f: float,
    threshold_f: float,
) -> dict:
    """Build a settlement lag signal dict."""
    return {
        "ticker": ticker,
        "city": city,
        "outcome": outcome,
        "confidence": confidence,
        "current_temp_f": current_temp_f,
        "threshold_f": threshold_f,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": "metar_settlement_lag",
    }


def write_settlement_signals(signals: list[dict]) -> None:
    """Write signals list to the signals file (atomic write)."""
    import safe_io
    safe_io.atomic_write_json({"signals": signals, "updated_at": datetime.now(timezone.utc).isoformat()}, _SIGNALS_PATH)


def read_settlement_signals(max_age_minutes: int = 120) -> list[dict]:
    """
    Read active settlement signals, filtering out expired ones.

    Args:
        max_age_minutes: Discard signals older than this many minutes

    Returns:
        List of active signal dicts
    """
    if not _SIGNALS_PATH.exists():
        return []
    try:
        data = json.loads(_SIGNALS_PATH.read_text())
        signals = data.get("signals", [])
    except Exception:
        return []

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=max_age_minutes)
    active = []
    for s in signals:
        try:
            created = datetime.fromisoformat(s["created_at"].replace("Z", "+00:00"))
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            if created >= cutoff:
                active.append(s)
        except Exception:
            pass
    return active


def check_city_settlement(city: str, active_tickers: list[dict]) -> list[dict]:
    """
    Check METAR for a city and return any new settlement signals.

    Args:
        city: City code (e.g. "NYC")
        active_tickers: List of active market dicts with ticker, threshold, direction

    Returns:
        List of new settlement signal dicts
    """
    from metar import fetch_metar, check_metar_lockout

    config = _MONITOR_CITIES.get(city)
    if not config:
        return []

    obs = fetch_metar(config["station"])
    if not obs:
        return []

    new_signals = []
    for market in active_tickers:
        threshold_f = float(market.get("threshold", 0))
        direction = market.get("direction", "above")
        if not threshold_f:
            continue

        lockout = check_metar_lockout(
            current_temp_f=obs["current_temp_f"],
            threshold_f=threshold_f,
            direction=direction,
            obs_time=obs["obs_time"],
            city_tz=config["tz"],
            margin_f=_SETTLEMENT_MARGIN_F,
        )
        if lockout["locked"]:
            signal = build_settlement_signal(
                ticker=market["ticker"],
                city=city,
                outcome=lockout["outcome"],
                confidence=lockout["confidence"],
                current_temp_f=obs["current_temp_f"],
                threshold_f=threshold_f,
            )
            new_signals.append(signal)
            _log.info(
                "SETTLEMENT LAG signal: %s → %s (conf=%.0f%%) — temp %.1f°F vs threshold %.1f°F",
                market["ticker"], lockout["outcome"], lockout["confidence"] * 100,
                obs["current_temp_f"], threshold_f,
            )

    return new_signals


def run_settlement_monitor(client, duration_minutes: int = 120) -> None:
    """
    Run the settlement lag monitoring loop.

    Polls METAR every _POLL_INTERVAL_SECONDS seconds, writing signals for any
    markets where the outcome has been confirmed.

    Args:
        client: Kalshi API client (for fetching active markets)
        duration_minutes: How long to run (default 2 hours)
    """
    _log.info("Settlement lag monitor starting (duration=%dmin)", duration_minutes)
    end_time = datetime.now(timezone.utc) + timedelta(minutes=duration_minutes)

    all_signals: list[dict] = []

    while datetime.now(timezone.utc) < end_time:
        for city in _MONITOR_CITIES:
            try:
                # Fetch active markets for this city from Kalshi
                # This is a placeholder — wire in the actual market fetch
                active_tickers: list[dict] = []
                try:
                    markets = client.get_markets(series_ticker=f"KXHIGH{city}")
                    for m in (markets or []):
                        if m.get("status") == "open":
                            ticker = m.get("ticker", "")
                            # Parse threshold from ticker or subtitle
                            subtitle = m.get("subtitle", "")
                            # Example: "NYC high temp above 72°F" → threshold=72
                            import re
                            match = re.search(r"(\d+)", subtitle)
                            if match:
                                threshold = float(match.group(1))
                                direction = "above" if "above" in subtitle.lower() else "below"
                                active_tickers.append({
                                    "ticker": ticker,
                                    "threshold": threshold,
                                    "direction": direction,
                                })
                except Exception as exc:
                    _log.debug("settlement_monitor: market fetch for %s: %s", city, exc)

                new = check_city_settlement(city, active_tickers)
                all_signals.extend(new)
            except Exception as exc:
                _log.debug("settlement_monitor: %s error: %s", city, exc)

        if all_signals:
            write_settlement_signals(all_signals)

        time.sleep(_POLL_INTERVAL_SECONDS)

    _log.info("Settlement lag monitor complete. %d signals written.", len(all_signals))
```

- [ ] **Step 4: Add `cmd_settlement_monitor` to `main.py`**

```python
def cmd_settlement_monitor(args: list[str] | None = None) -> None:
    """Run METAR settlement lag monitor (polls from 5-7 PM local time)."""
    from settlement_monitor import run_settlement_monitor
    from kalshi_client import get_client

    duration = 120
    if args:
        try:
            duration = int(args[0])
        except ValueError:
            pass

    _log.info("Starting settlement monitor for %d minutes...", duration)
    client = get_client(live=False)
    run_settlement_monitor(client, duration_minutes=duration)
```

Wire into dispatch:
```python
"settlement-monitor": lambda a: cmd_settlement_monitor(a),
"settle": lambda a: cmd_settlement_monitor(a),
```

- [ ] **Step 5: Run tests to verify they pass**

```
python -m pytest tests/test_settlement_monitor.py -v
```

Expected: 4 tests PASSED

- [ ] **Step 6: Run full test suite**

```
python -m pytest -x -q
```

Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add settlement_monitor.py tests/test_settlement_monitor.py web_app.py templates/analytics.html tracker.py main.py
git commit -m "feat(phase-d): monitoring complete — settlement lag monitor + per-city Brier + reliability diagram"
```
