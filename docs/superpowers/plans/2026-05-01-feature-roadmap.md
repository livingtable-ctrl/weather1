# Feature Roadmap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve Brier score from ~0.235 to below 0.20 and add operational reliability features to the Kalshi weather prediction paper trading system.

**Architecture:** Eight independent phases ordered by expected Brier improvement and implementation effort. Each phase is self-contained — implement them in order or skip phases that require more data than is available. All new modules follow the existing pattern: standalone `.py` file, TDD, ruff+mypy clean, committed before moving on.

**Tech Stack:** Python 3.12+, SQLite (`data/predictions.db`), Open-Meteo API (ensemble members), NWS API, scikit-learn (Platt scaling), smtplib / requests (reporting), existing `utils.normal_cdf`, `calibration.py`, `weather_markets.py`, `nws.py`, `cron.py`, `main.py`

---

## Bugs to fix (from 2026-05-01 Cursor audit)

These should be fixed before implementing any new phases.

| # | Priority | Summary | Files |
|---|----------|---------|-------|
| B1 | P0 | Backtest NO-side entry uses `no_bid` — should use `1 - yes_bid` (same as live pricing) | `backtest.py` |
| B2 | P0 | Precip backtest sets `our_prob` from realized obs (lookahead leakage) — use forecast prob at trade time | `backtest.py` |
| B3 | P1 | Graduation criteria UX mismatch — menu says 20 trades/55% win rate, code requires 30 trades/Brier≤0.20/$50 P&L | `main.py` |
| B4 | P1 | `DRAWDOWN_HALT_PCT` default inconsistency — README says 0.50, code defaults to 0.20, paper.py comment says 50% | `README`, `paper.py` |

> **Note on B3 and B4:** These are trivial string/comment fixes — do them in Cursor directly.
> **Note on B1 and B2:** Non-trivial backtest logic — fix via Claude Code to avoid regressions.

---

## Phase overview (implement in this order)

| Phase | Feature | Est. Brier gain | Effort | Data prereq |
|-------|---------|----------------|--------|------------|
| 1 | Full ensemble CDF (replaces NBM approx) | −0.03 to −0.05 | 1 week | None |
| 4 | Automated daily report | Operational | 2 days | None |
| 8 | Live trading readiness gate | Safety | 1 day | None |
| 2 | Per-city Platt scaling | −0.02 to −0.04 | 3 days | 200+ trades/city |
| 3 | Portfolio correlation Kelly | Risk reduction | 3 days | None |
| 5 | Condition-type calibration + per-type weights | −0.01 to −0.02 | 4 days | 100+ per type |
| 7 | Market anomaly detection | Win rate | 2 days | None |
| 6 | Dynamic obs weight | −0.01 to −0.02 | 1 week | 500+ trades + DB migration |

> **Phases 4 and 8 have no data dependency** — do them immediately after Phase 1 while data accumulates for Phases 2 and 5.

---

## Phase 1: Full Ensemble CDF Integration

**Why first and why not NWS quantiles:**
The original plan proposed fetching NWS gridpoints for NBM quantile data. That was wrong — the NWS gridpoints endpoint returns deterministic (single-value) forecasts, not quantiles. True NBM probabilistic data lives in GRIB2 files on NOMADS which are complex to parse.

The correct approach: **Open-Meteo already provides 51 ensemble members** via `models=ensemble_seamless&hourly=temperature_2m_max&ensemble=true`. The system currently uses only the ensemble mean and std. Using all 51 members gives us the empirical CDF directly — `P(high > threshold)` computed by counting how many of the 51 members exceed the threshold. No GRIB2, no approximation, no new API dependency.

**Files:**
- Modify: `weather_markets.py` — `get_weather_forecast()` to fetch all ensemble members; new helper `ensemble_cdf_prob()`
- Modify: `weather_markets.py` — `_src_probs` block to add `"ensemble_cdf"` source
- Test: `tests/test_gaussian_prob.py` (append)

---

### Task 1.1: Fetch all 51 ensemble members from Open-Meteo

- [ ] **Step 1: Write the failing test**

```python
# Append to tests/test_gaussian_prob.py

def test_fetch_ensemble_members_returns_list():
    """get_ensemble_members returns a list of ≥10 floats on success."""
    from unittest.mock import MagicMock, patch
    import weather_markets as wm

    # Open-Meteo ensemble API returns hourly data per member.
    # ECMWF IFS04 members are 1-indexed: member01 through member51.
    # We compute daily max by taking max of all hourly values per member.
    fake_hourly: dict = {"time": ["2026-05-05T00:00", "2026-05-05T12:00"]}
    for i in range(1, 52):
        key = f"temperature_2m_member{i:02d}"
        # °C values; 20.0 → 68°F, 21.0 → 69.8°F
        fake_hourly[key] = [20.0 + i * 0.1, 20.5 + i * 0.1]
    fake_resp_json = {"hourly": fake_hourly}

    mock_response = MagicMock()
    mock_response.json.return_value = fake_resp_json

    with patch("weather_markets._om_request", return_value=mock_response):
        members = wm.get_ensemble_members(40.77, -73.96, "2026-05-05", var="max")

    assert members is not None
    assert len(members) >= 10
    # Values should be in °F (converted from °C ~20 → ~68°F)
    assert all(60.0 < m < 85.0 for m in members)


def test_get_ensemble_members_returns_none_on_failure():
    """get_ensemble_members returns None when the API errors."""
    from unittest.mock import patch
    import weather_markets as wm

    with patch("weather_markets._om_request", side_effect=Exception("timeout")):
        result = wm.get_ensemble_members(40.77, -73.96, "2026-05-05", var="max")

    assert result is None
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_gaussian_prob.py::test_fetch_ensemble_members_returns_list -v
```
Expected: `AttributeError: module 'weather_markets' has no attribute 'get_ensemble_members'`

- [ ] **Step 3: Add `get_ensemble_members` to `weather_markets.py`**

Add after the existing `get_weather_forecast` function:

```python
def get_ensemble_members(
    lat: float,
    lon: float,
    target_date_str: str,
    var: str = "max",
) -> list[float] | None:
    """
    Fetch all 51 ECMWF IFS04 ensemble members for daily high (var='max') or
    low (var='min') temperature on target_date.  Returns values in °F.

    API note: the Open-Meteo ensemble endpoint returns **hourly** temperature
    per member (temperature_2m_member01 … temperature_2m_member51, 1-indexed).
    There is no per-member daily aggregate endpoint — we compute daily high/low
    by taking max/min of all hourly values for the target date per member.

    Uses _om_request (rate-limited, retried) — same as all other OM calls.
    """
    import json
    from pathlib import Path

    cache_dir = Path(__file__).parent / "data" / "ensemble_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f"{lat:.3f}_{lon:.3f}_{target_date_str}_{var}.json"
    if cache_file.exists():
        try:
            return json.loads(cache_file.read_text())
        except Exception:
            pass

    try:
        resp = _om_request(
            "GET",
            ENSEMBLE_BASE,
            params={
                "latitude": lat,
                "longitude": lon,
                "hourly": "temperature_2m",
                "temperature_unit": "fahrenheit",
                "models": "ecmwf_ifs04",
                "start_date": target_date_str,
                "end_date": target_date_str,
                "timezone": "UTC",
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        _log.debug("Ensemble member fetch failed: %s", e)
        return None

    hourly = data.get("hourly", {})
    members: list[float] = []
    # ECMWF IFS04: 51 members, 1-indexed (member01 … member51)
    for i in range(1, 52):
        key = f"temperature_2m_member{i:02d}"
        vals = [v for v in hourly.get(key, []) if v is not None]
        if vals:
            daily_val = max(vals) if var == "max" else min(vals)
            members.append(float(daily_val))

    if len(members) < 10:
        _log.debug("Ensemble member fetch: only %d members returned", len(members))
        return None

    try:
        cache_file.write_text(json.dumps(members))
    except Exception:
        pass

    return members
```

- [ ] **Step 4: Run tests to verify pass**

```bash
pytest tests/test_gaussian_prob.py -k ensemble_members -v
```
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add weather_markets.py tests/test_gaussian_prob.py
git commit -m "feat(forecast): fetch all 51 Open-Meteo ensemble members for empirical CDF"
```

---

### Task 1.2: Empirical CDF probability function

- [ ] **Step 1: Write the failing test**

```python
# Append to tests/test_gaussian_prob.py

def test_ensemble_cdf_prob_above_at_median():
    """50th-percentile threshold → P(above) near 0.50."""
    import weather_markets as wm
    import statistics

    members = list(range(60, 111))  # 51 values: 60–110°F
    median = statistics.median(members)  # 85°F
    p = wm.ensemble_cdf_prob(members, {"type": "above", "threshold": median})
    assert 0.45 <= p <= 0.55


def test_ensemble_cdf_prob_below_threshold_below_all():
    """Threshold below all members → P(above) near 1.0."""
    import weather_markets as wm

    members = [70.0] * 51
    p = wm.ensemble_cdf_prob(members, {"type": "above", "threshold": 50.0})
    assert p > 0.95


def test_ensemble_cdf_prob_between():
    """P(between) counts members in range."""
    import weather_markets as wm

    # 51 members: 10 between 69-71, rest outside
    members = [65.0] * 20 + [70.0] * 11 + [75.0] * 20
    p = wm.ensemble_cdf_prob(members, {"type": "between", "lower": 69.0, "upper": 71.0})
    assert abs(p - 11 / 51) < 0.02
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_gaussian_prob.py -k ensemble_cdf_prob -v
```
Expected: `AttributeError: module 'weather_markets' has no attribute 'ensemble_cdf_prob'`

- [ ] **Step 3: Add `ensemble_cdf_prob` to `weather_markets.py`**

```python
def ensemble_cdf_prob(members: list[float], condition: dict) -> float:
    """
    Compute P(outcome | condition) from raw ensemble members via empirical CDF.
    More accurate than Gaussian approximation for skewed or bimodal distributions.

    Args:
        members: list of forecast values in °F (e.g., 51 ensemble members)
        condition: {"type": "above"/"below"/"between", "threshold"/"lower"/"upper"}
    """
    if not members:
        return 0.5

    n = len(members)
    ctype = condition["type"]

    if ctype == "above":
        return sum(1 for m in members if m > condition["threshold"]) / n
    elif ctype == "below":
        return sum(1 for m in members if m < condition["threshold"]) / n
    elif ctype == "between":
        lo, hi = condition["lower"], condition["upper"]
        return sum(1 for m in members if lo <= m <= hi) / n

    return 0.5
```

- [ ] **Step 4: Run tests to verify pass**

```bash
pytest tests/test_gaussian_prob.py -k "ensemble_cdf" -v
```
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add weather_markets.py tests/test_gaussian_prob.py
git commit -m "feat(forecast): empirical CDF probability from ensemble members"
```

---

### Task 1.3: Wire ensemble CDF into the blend pipeline

- [ ] **Step 1: Write the failing test**

```python
# Append to tests/test_gaussian_prob.py

def test_analyze_trade_includes_ensemble_cdf_in_blend_sources(monkeypatch):
    """When get_ensemble_members succeeds, blend_sources includes 'ensemble_cdf'."""
    from unittest.mock import MagicMock, patch
    import weather_markets as wm

    fake_members = [68.0 + i * 0.2 for i in range(51)]

    market = {
        "ticker": "KXHIGHNY-26MAY10-T72",
        "title": "NYC high > 72°F?",
        "yes_bid": 40, "yes_ask": 44, "no_bid": 56,
        "volume": 300, "open_interest": 150,
        "close_time": "2026-05-10T23:00:00Z",
    }

    with (
        patch("weather_markets.get_weather_forecast",
              return_value={"temp_f": 72.0, "sigma_f": 4.0, "fetched_at": None}),
        patch("weather_markets.get_climatology_prob", return_value=0.50),
        patch("weather_markets.get_nws_forecast_prob", return_value=None),
        patch("weather_markets.get_ensemble_members", return_value=fake_members),
    ):
        result = wm.analyze_trade(market, MagicMock())

    assert result is not None
    src = result.get("blend_sources", {})
    assert "ensemble_cdf" in src, f"ensemble_cdf missing from blend_sources: {src}"
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_gaussian_prob.py::test_analyze_trade_includes_ensemble_cdf_in_blend_sources -v
```
Expected: FAIL — `AssertionError: ensemble_cdf missing`

- [ ] **Step 3: Add ensemble CDF to `analyze_trade` in `weather_markets.py`**

In `analyze_trade`, after the existing ensemble probability computation, add:

```python
# Empirical CDF from full ensemble members (51-member distribution)
_ensemble_cdf_prob: float | None = None
try:
    _members = get_ensemble_members(lat, lon, target_date.isoformat(), var=var)
    if _members:
        _ensemble_cdf_prob = ensemble_cdf_prob(_members, condition)
except Exception:
    pass
```

In the `_src_probs` list, replace the raw `ens_prob` entry with a split:
- Keep `ens_prob` (Gaussian ensemble) at reduced weight (e.g. `_w_ens_final * 0.5`)
- Add `_ensemble_cdf_prob` at weight `_w_ens_final * 0.5` when available, else fall back to full `_w_ens_final` for Gaussian alone

```python
_w_gauss_ens = _w_ens_final * (0.5 if _ensemble_cdf_prob is not None else 1.0)
_w_cdf_ens   = _w_ens_final * (0.5 if _ensemble_cdf_prob is not None else 0.0)

_src_probs = [
    (_w_gauss_ens, ens_prob),
    (_w_cdf_ens,   _ensemble_cdf_prob),
    (_w_gauss,     gauss_prob),
    (w_clim,       clim_prob),
    (w_nws,        _nws_prob),
    (w_persist,    persistence_p),
]
```

In `blend_sources` reporting dict, add:
```python
"ensemble_cdf": round(_ensemble_cdf_prob, 4) if _ensemble_cdf_prob is not None else None,
```

- [ ] **Step 4: Run full test suite**

```bash
pytest tests/ -x -q
```
Expected: all existing tests pass plus the new one

- [ ] **Step 5: Commit**

```bash
git add weather_markets.py tests/test_gaussian_prob.py
git commit -m "feat(forecast): wire 51-member empirical CDF into blend at 50% of ensemble weight"
```

---

## Phase 4: Automated Daily Report

**Why now:** No data dependency. Takes 2 days. You'll see P&L and Brier drift every morning without running manual commands.

**Files:**
- Create: `daily_report.py`
- Modify: `cron.py` (call at end of daily run)
- Test: `tests/test_daily_report.py`

---

### Task 4.1: Report generator

- [ ] **Step 1: Write the failing test**

```python
# tests/test_daily_report.py
import sqlite3, tempfile, os
from pathlib import Path


def _make_db(path: str) -> None:
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE IF NOT EXISTS predictions (
            id INTEGER PRIMARY KEY,
            market_date TEXT,
            city TEXT,
            our_prob REAL,
            settled_yes INTEGER,
            created_at TEXT
        );
        INSERT INTO predictions VALUES
            (1, '2026-05-01', 'NYC', 0.70, 1, '2026-05-01T10:00:00'),
            (2, '2026-05-01', 'Chicago', 0.60, 0, '2026-05-01T10:00:00'),
            (3, '2026-05-01', 'Miami', 0.80, 1, '2026-05-01T10:00:00');
    """)
    con.commit()
    con.close()


def test_generate_report_has_required_sections():
    """Daily report string includes Brier score, trade count, and city names."""
    import daily_report

    with tempfile.TemporaryDirectory() as d:
        db = os.path.join(d, "predictions.db")
        _make_db(db)
        report = daily_report.generate_daily_report(db_path=db, lookback_days=1)

    assert "brier" in report.lower()
    assert "nyc" in report.lower()
    assert "3" in report  # 3 trades


def test_generate_report_no_trades_message():
    """When no settled trades exist, report says so clearly."""
    import daily_report

    with tempfile.TemporaryDirectory() as d:
        db = os.path.join(d, "predictions.db")
        con = sqlite3.connect(db)
        con.execute(
            "CREATE TABLE predictions "
            "(id INTEGER PRIMARY KEY, market_date TEXT, city TEXT, "
            "our_prob REAL, settled_yes INTEGER, created_at TEXT)"
        )
        con.commit()
        con.close()
        report = daily_report.generate_daily_report(db_path=db, lookback_days=1)

    assert "no settled" in report.lower() or "0 trades" in report.lower()


def test_send_slack_posts_to_webhook(monkeypatch):
    """send_daily_report calls requests.post when SLACK_WEBHOOK_URL is set."""
    import daily_report

    posted = {}

    def _fake_post(url, json=None, timeout=None):
        posted["url"] = url
        posted["body"] = json
        class R:
            status_code = 200
        return R()

    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/fake")
    monkeypatch.setattr("requests.post", _fake_post)

    daily_report.send_daily_report("Test report body")
    assert "hooks.slack.com" in posted.get("url", "")
    assert "Test report body" in str(posted.get("body", ""))
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_daily_report.py -v
```
Expected: `ModuleNotFoundError: No module named 'daily_report'`

- [ ] **Step 3: Implement `daily_report.py`**

```python
# daily_report.py
"""
Generate and deliver a daily summary: Brier, win rate, per-city breakdown.

Delivery via env vars:
  SLACK_WEBHOOK_URL          — Slack incoming webhook
  REPORT_EMAIL_TO            — recipient address
  SMTP_HOST / SMTP_PORT      — SMTP server (defaults: localhost / 587)
  SMTP_USER / SMTP_PASS      — credentials
"""
from __future__ import annotations

import os
import sqlite3
import statistics
from datetime import date, timedelta
from pathlib import Path


def generate_daily_report(
    db_path: str | None = None,
    lookback_days: int = 1,
) -> str:
    if db_path is None:
        db_path = str(Path(__file__).parent / "data" / "predictions.db")

    cutoff = (date.today() - timedelta(days=lookback_days)).isoformat()

    with sqlite3.connect(db_path) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT city, our_prob, settled_yes, market_date "
            "FROM predictions "
            "WHERE settled_yes IS NOT NULL AND our_prob IS NOT NULL "
            "AND market_date >= ?",
            (cutoff,),
        ).fetchall()

    if not rows:
        return (
            f"Daily Report — {date.today()}\n"
            f"{'='*40}\n"
            f"No settled trades in the last {lookback_days} day(s).\n"
        )

    briers = [(r["our_prob"] - r["settled_yes"]) ** 2 for r in rows]
    wins = sum(
        1 for r in rows if (r["our_prob"] > 0.5) == bool(r["settled_yes"])
    )
    mean_brier = statistics.mean(briers)
    win_rate = wins / len(rows)

    by_city: dict[str, list[float]] = {}
    for r in rows:
        by_city.setdefault(r["city"], []).append(
            (r["our_prob"] - r["settled_yes"]) ** 2
        )

    city_lines = "\n".join(
        f"  {city:<15} n={len(bs):<4} Brier={statistics.mean(bs):.3f}"
        for city, bs in sorted(by_city.items())
    )

    target_marker = " ✓" if mean_brier < 0.20 else " ← target <0.20"
    return (
        f"Daily Report — {date.today()}\n"
        f"{'='*40}\n"
        f"Trades settled : {len(rows)}\n"
        f"Win rate       : {win_rate:.1%}\n"
        f"Mean Brier     : {mean_brier:.4f}{target_marker}\n"
        f"\nPer-city breakdown:\n{city_lines}\n"
    )


def send_daily_report(body: str) -> None:
    slack_url = os.getenv("SLACK_WEBHOOK_URL")
    if slack_url:
        try:
            import requests
            requests.post(slack_url, json={"text": body}, timeout=10)
        except Exception as e:
            print(f"[report] Slack send failed: {e}")

    email_to = os.getenv("REPORT_EMAIL_TO")
    if email_to:
        try:
            import smtplib
            from email.message import EmailMessage

            msg = EmailMessage()
            msg["Subject"] = f"Weather Trader Daily Report — {date.today()}"
            msg["From"] = os.getenv("SMTP_USER", "trader@localhost")
            msg["To"] = email_to
            msg.set_content(body)

            with smtplib.SMTP(
                os.getenv("SMTP_HOST", "localhost"),
                int(os.getenv("SMTP_PORT", "587")),
            ) as smtp:
                user = os.getenv("SMTP_USER")
                pw = os.getenv("SMTP_PASS")
                if user and pw:
                    smtp.starttls()
                    smtp.login(user, pw)
                smtp.send_message(msg)
        except Exception as e:
            print(f"[report] Email send failed: {e}")
```

- [ ] **Step 4: Run tests to verify pass**

```bash
pytest tests/test_daily_report.py -v
```
Expected: 4 passed

- [ ] **Step 5: Call from `cron.py` at end of daily run**

At the end of `cmd_cron`, after `auto_settle_paper_trades`:

```python
try:
    from daily_report import generate_daily_report, send_daily_report
    _report_body = generate_daily_report()
    print(_report_body)
    send_daily_report(_report_body)
except Exception as _e:
    _log.warning("Daily report failed: %s", _e)
```

- [ ] **Step 6: Commit**

```bash
git add daily_report.py tests/test_daily_report.py cron.py
git commit -m "feat(ops): automated daily Brier/win-rate report via Slack or email"
```

---

## Phase 8: Live Trading Readiness Gate

**Why now:** No data dependency. 1 day of work. Prevents accidentally going live before the model is ready.

**Files:**
- Modify: `main.py` (add `cmd_readiness`, wire to `"readiness"` CLI arg)
- Test: `tests/test_trading.py` (append)

---

### Task 8.1: Readiness check command

- [ ] **Step 1: Write the failing test**

```python
# Append to tests/test_trading.py

def test_cmd_readiness_fails_when_brier_above_threshold(monkeypatch, capsys):
    """cmd_readiness returns False and prints FAIL when Brier > 0.20."""
    from unittest.mock import MagicMock
    import main

    monkeypatch.setattr(
        "backtest.run_backtest",
        lambda *a, **kw: {"brier": 0.28, "roc_auc": 0.65, "n_trades": 120},
    )
    monkeypatch.setattr("main._get_current_drawdown", lambda: 0.05)
    monkeypatch.setattr("main._circuit_breaker_open", lambda: False)

    result = main.cmd_readiness(MagicMock())
    out = capsys.readouterr().out

    assert result is False
    assert "FAIL" in out or "✗" in out


def test_cmd_readiness_passes_when_all_gates_clear(monkeypatch, capsys):
    """cmd_readiness returns True only when all 5 gates pass."""
    from unittest.mock import MagicMock
    import main

    monkeypatch.setattr(
        "backtest.run_backtest",
        lambda *a, **kw: {"brier": 0.18, "roc_auc": 0.67, "n_trades": 120},
    )
    monkeypatch.setattr("main._get_current_drawdown", lambda: 0.05)
    monkeypatch.setattr("main._circuit_breaker_open", lambda: False)

    result = main.cmd_readiness(MagicMock())
    out = capsys.readouterr().out

    assert result is True
    assert "PASS" in out or "✓" in out
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_trading.py -k readiness -v
```
Expected: `AttributeError: module 'main' has no attribute 'cmd_readiness'`

- [ ] **Step 3: Add helper wrappers and `cmd_readiness` to `main.py`**

First add these two thin wrappers near the top of `main.py` (alongside other module-level helpers).
They exist as named functions so the tests can monkeypatch `main._get_current_drawdown` and
`main._circuit_breaker_open` without touching the underlying modules.

```python
def _get_current_drawdown() -> float:
    """Return peak-to-trough drawdown fraction (0.0–1.0). Wraps paper.get_max_drawdown_pct."""
    from paper import get_max_drawdown_pct
    try:
        return float(get_max_drawdown_pct())
    except Exception:
        return 0.0


def _circuit_breaker_open() -> bool:
    """Return True when the flash-crash circuit breaker is currently open."""
    from circuit_breaker import flash_crash_cb
    try:
        return bool(flash_crash_cb.is_open())
    except Exception:
        return False
```

Then add `cmd_readiness`:

```python
def cmd_readiness(client) -> bool:
    """
    Run pre-live-trading checklist.  Returns True only if ALL gates pass.
    Usage: py main.py readiness
    Exit code: 0 = ready, 1 = not ready.

    Gates:
      1. Brier < 0.20 over last 60 days (needs 50+ trades)
      2. ROC-AUC > 0.60 over last 60 days
      3. At least 50 settled trades in the last 60 days
      4. Drawdown < 10%
      5. No circuit breaker currently open
    """
    import backtest as _bt

    _header("Live Trading Readiness Check")
    gates: list[tuple[str, bool, str]] = []

    try:
        bt = _bt.run_backtest(client, days=60)
        brier = bt.get("brier", 1.0)
        roc   = bt.get("roc_auc", 0.0)
        n     = bt.get("n_trades", 0)
        gates.append(("Brier < 0.20  (60d)", brier < 0.20, f"Brier={brier:.4f}  n={n}"))
        gates.append(("ROC-AUC > 0.60 (60d)", roc > 0.60,  f"ROC-AUC={roc:.3f}"))
        gates.append(("≥50 trades     (60d)", n >= 50,      f"n={n}"))
    except Exception as e:
        gates.append(("Backtest", False, f"Error: {e}"))

    try:
        dd = _get_current_drawdown()
        gates.append(("Drawdown < 10%", dd < 0.10, f"drawdown={dd:.1%}"))
    except Exception:
        gates.append(("Drawdown", False, "Could not compute"))

    try:
        cb = _circuit_breaker_open()
        gates.append(("Circuit breaker closed", not cb, "open" if cb else "closed"))
    except Exception:
        gates.append(("Circuit breaker", False, "Could not check"))

    all_pass = True
    for label, passed, detail in gates:
        icon = green("✓ PASS") if passed else red("✗ FAIL")
        print(f"  {icon}  {label:<30} {dim(detail)}")
        if not passed:
            all_pass = False

    print()
    if all_pass:
        print(green("  ✓ ALL GATES PASSED — system is ready for live trading"))
    else:
        print(red("  ✗ NOT READY — fix failing gates before going live"))

    return all_pass
```

Wire to CLI in `main()`:
```python
elif cmd == "readiness":
    ready = cmd_readiness(client)
    sys.exit(0 if ready else 1)
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_trading.py -k readiness -v
```
Expected: both pass

- [ ] **Step 5: Commit**

```bash
git add main.py tests/test_trading.py
git commit -m "feat(safety): py main.py readiness — live trading gate with 5 checks"
```

---

## Phase 2: Per-City Platt Scaling

**Prerequisite:** 200+ settled predictions per city. Check with:
```bash
python -c "
import sqlite3
con = sqlite3.connect('data/predictions.db')
for row in con.execute('SELECT city, count(*) FROM predictions WHERE settled_yes IS NOT NULL GROUP BY city ORDER BY 2 DESC'):
    print(row)
"
```
Skip this phase until at least one city hits 200.

**Files:**
- Modify: `ml_bias.py` (add `train_platt_per_city`, `apply_platt_per_city`)
- Modify: `main.py` (`cmd_calibrate` trains and saves; `analyze_trade` applies)
- Test: `tests/test_ml_bias.py` (append or create)

---

### Task 2.1: Train and apply per-city Platt scaling

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ml_bias.py (append or create)
import random


def test_train_platt_per_city_returns_coefficients():
    """train_platt_per_city returns {city: (A, B)} for cities with >=200 samples."""
    import ml_bias

    random.seed(42)
    rows = []
    for _ in range(250):
        p = random.uniform(0.3, 0.8)
        rows.append({"city": "NYC", "our_prob": p,
                     "settled_yes": 1 if random.random() < p else 0})
    for _ in range(50):
        rows.append({"city": "Chicago", "our_prob": 0.6, "settled_yes": 1})

    models = ml_bias.train_platt_per_city(rows, min_samples=200)

    assert "NYC" in models, "NYC (250 samples) must be trained"
    assert "Chicago" not in models, "Chicago (<200) must be skipped"
    a, b = models["NYC"]
    assert isinstance(a, float) and isinstance(b, float)


def test_apply_platt_per_city_unknown_city_unchanged():
    """Unknown city returns raw prob unchanged."""
    import ml_bias
    p = ml_bias.apply_platt_per_city("Dallas", 0.65, {})
    assert p == pytest.approx(0.65)


def test_apply_platt_identity_calibration():
    """A=1.0, B=0.0 (identity) returns approximately the input probability."""
    import ml_bias
    models = {"NYC": (1.0, 0.0)}
    p = ml_bias.apply_platt_per_city("NYC", 0.70, models)
    assert 0.60 <= p <= 0.80
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_ml_bias.py -v
```
Expected: `AttributeError: module 'ml_bias' has no attribute 'train_platt_per_city'`

- [ ] **Step 3: Add to `ml_bias.py`**

Note: uses `scipy.optimize.minimize` — already in `requirements.txt`. No sklearn needed.

```python
import math
from collections import defaultdict


def _logit(p: float) -> float:
    p = max(1e-6, min(1 - 1e-6, p))
    return math.log(p / (1 - p))


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _fit_platt(xs: list[float], ys: list[int]) -> tuple[float, float]:
    """
    Fit Platt scaling (A, B) via cross-entropy minimisation with scipy.
    calibrated_prob = sigmoid(A * x + B) where x = logit(raw_prob).
    Uses scipy.optimize — already in requirements.txt, no sklearn needed.
    """
    from scipy.optimize import minimize  # type: ignore[import-untyped]
    import numpy as np

    xa = np.array(xs, dtype=float)
    ya = np.array(ys, dtype=float)

    def neg_log_likelihood(params: np.ndarray) -> float:
        a, b = params
        p = 1.0 / (1.0 + np.exp(-(a * xa + b)))
        p = np.clip(p, 1e-9, 1 - 1e-9)
        return -float(np.sum(ya * np.log(p) + (1 - ya) * np.log(1 - p)))

    res = minimize(neg_log_likelihood, x0=[1.0, 0.0], method="L-BFGS-B")
    return float(res.x[0]), float(res.x[1])


def train_platt_per_city(
    rows: list[dict],
    min_samples: int = 200,
) -> dict[str, tuple[float, float]]:
    """
    Train per-city Platt scaling: fits (A, B) via cross-entropy on logit(p).
    Returns {city: (A, B)} where calibrated_prob = sigmoid(A * logit(p) + B).
    Skips cities with fewer than min_samples settled predictions.
    """
    by_city: dict[str, list] = defaultdict(list)
    for r in rows:
        city, p, y = r.get("city"), r.get("our_prob"), r.get("settled_yes")
        if city and p is not None and y is not None:
            try:
                by_city[city].append((_logit(float(p)), int(y)))
            except (ValueError, TypeError):
                pass

    result: dict[str, tuple[float, float]] = {}
    for city, samples in by_city.items():
        if len(samples) < min_samples:
            continue
        try:
            xs = [x for x, _ in samples]
            ys = [label for _, label in samples]
            result[city] = _fit_platt(xs, ys)
        except Exception:
            pass

    return result


def apply_platt_per_city(
    city: str,
    raw_prob: float,
    models: dict[str, tuple[float, float]],
) -> float:
    """Apply per-city Platt calibration; returns raw_prob unchanged if no model."""
    if city not in models:
        return raw_prob
    a, b = models[city]
    return _sigmoid(a * _logit(raw_prob) + b)
```

- [ ] **Step 4: Wire into `cmd_calibrate` in `main.py`**

In `cmd_calibrate`, after existing calibration, add:

```python
import json as _json
from ml_bias import train_platt_per_city

if db_path.exists():
    with sqlite3.connect(db_path) as _con:
        _con.row_factory = sqlite3.Row
        _rows = [dict(r) for r in _con.execute(
            "SELECT city, our_prob, settled_yes FROM predictions "
            "WHERE settled_yes IS NOT NULL AND our_prob IS NOT NULL"
        ).fetchall()]
    platt = train_platt_per_city(_rows, min_samples=200)
    if platt:
        _platt_path = data_dir / "platt_models.json"
        _platt_path.write_text(_json.dumps(platt, indent=2))
        print(green(f"  Platt models trained: {', '.join(sorted(platt))}"))
    else:
        print(dim("  Platt: need 200+ settled trades per city (not yet)"))
```

- [ ] **Step 5: Apply in `weather_markets.py`**

After `apply_ml_prob_correction` (~line 3937), add:

```python
try:
    import json as _j
    from pathlib import Path as _P
    _platt_path = _P(__file__).parent / "data" / "platt_models.json"
    if _platt_path.exists():
        from ml_bias import apply_platt_per_city as _apply_platt
        _platt_models = _j.loads(_platt_path.read_text())
        blended_prob = _apply_platt(city, blended_prob, _platt_models)
except Exception:
    pass
```

- [ ] **Step 6: Run tests**

```bash
pytest tests/test_ml_bias.py -v && pytest tests/ -q
```
Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add ml_bias.py main.py weather_markets.py tests/test_ml_bias.py
git commit -m "feat(calibration): per-city Platt scaling trained at 200+ trades per city"
```

---

## Phase 3: Portfolio Correlation-Aware Kelly Sizing

**Why:** NYC and Boston same-day markets are correlated ~0.85. Sizing them independently overstates diversification. This applies a penalty when correlated same-day positions are already open.

**Note on penalty strength:** The formula `kelly * (1 - corr * partner_kelly)` is intentionally mild (~8.5% reduction at 0.85 correlation with 0.10 partner Kelly). This is a safe starting point — tighten `max_portfolio_corr_penalty` upward (e.g. 0.75) after observing how often correlated cities fire together. A full Markowitz variance constraint would be more principled but requires estimating position variance.

**Files:**
- Create: `portfolio_corr.py`
- Modify: `main.py` (`_auto_place_trades`)
- Test: `tests/test_portfolio_corr.py`

---

### Task 3.1: Correlation penalty

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_portfolio_corr.py
import pytest


def test_correlated_cities_reduce_kelly():
    """NYC + Boston (corr=0.85) same-day reduces NYC Kelly."""
    from portfolio_corr import corr_adjusted_kelly

    solo = corr_adjusted_kelly("NYC", 0.10, [], "2026-05-05")
    with_boston = corr_adjusted_kelly(
        "NYC", 0.10,
        [{"city": "Boston", "kelly": 0.10, "target_date": "2026-05-05"}],
        "2026-05-05",
    )
    assert with_boston < solo
    assert with_boston > 0.0


def test_low_correlation_cities_minimal_reduction():
    """NYC + Phoenix (corr~0.15) barely reduces Kelly."""
    from portfolio_corr import corr_adjusted_kelly

    result = corr_adjusted_kelly(
        "NYC", 0.10,
        [{"city": "Phoenix", "kelly": 0.10, "target_date": "2026-05-05"}],
        "2026-05-05",
    )
    assert result >= 0.098  # <2% reduction for low-corr pair


def test_different_dates_no_penalty():
    """Same city, different date: correlation penalty does not apply."""
    from portfolio_corr import corr_adjusted_kelly

    result = corr_adjusted_kelly(
        "NYC", 0.10,
        [{"city": "NYC", "kelly": 0.10, "target_date": "2026-05-06"}],
        "2026-05-05",
    )
    assert result == pytest.approx(0.10)
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_portfolio_corr.py -v
```
Expected: `ModuleNotFoundError: No module named 'portfolio_corr'`

- [ ] **Step 3: Implement `portfolio_corr.py`**

```python
# portfolio_corr.py
"""
Correlation-aware Kelly sizing for multi-city same-day weather positions.

Penalty is mild by design — start conservative and raise max_portfolio_corr_penalty
toward 0.75 once you've observed how often correlated pairs fire together.
"""
from __future__ import annotations

_CITY_CORR: dict[frozenset, float] = {
    frozenset({"NYC", "Boston"}): 0.85,
    frozenset({"NYC", "Philadelphia"}): 0.88,
    frozenset({"NYC", "Washington"}): 0.82,
    frozenset({"Boston", "Philadelphia"}): 0.80,
    frozenset({"Chicago", "Minneapolis"}): 0.78,
    frozenset({"Chicago", "Detroit"}): 0.75,
    frozenset({"Dallas", "Houston"}): 0.80,
    frozenset({"Dallas", "SanAntonio"}): 0.78,
    frozenset({"LA", "SanFrancisco"}): 0.55,
    frozenset({"NYC", "Chicago"}): 0.55,
    frozenset({"NYC", "Miami"}): 0.25,
    frozenset({"NYC", "Denver"}): 0.20,
    frozenset({"NYC", "LA"}): 0.10,
    frozenset({"NYC", "Phoenix"}): 0.15,
    frozenset({"NYC", "Seattle"}): 0.15,
    frozenset({"Chicago", "Dallas"}): 0.45,
    frozenset({"Miami", "Dallas"}): 0.40,
    frozenset({"Denver", "Phoenix"}): 0.30,
}


def get_city_pair_corr(a: str, b: str) -> float:
    if a == b:
        return 1.0
    return _CITY_CORR.get(frozenset({a, b}), 0.10)


def corr_adjusted_kelly(
    city: str,
    kelly: float,
    open_positions: list[dict],
    target_date: str,
    max_portfolio_corr_penalty: float = 0.50,
) -> float:
    """
    Reduce Kelly by weighted correlation overlap with same-date open positions.

    To tighten: increase max_portfolio_corr_penalty toward 0.75.
    To loosen: decrease it toward 0.25.
    """
    if not open_positions or kelly <= 0:
        return kelly

    same_day = [p for p in open_positions if p.get("target_date") == target_date]
    if not same_day:
        return kelly

    overlap = sum(
        get_city_pair_corr(city, p["city"]) * p.get("kelly", 0.0)
        for p in same_day
    )
    penalty = min(overlap, max_portfolio_corr_penalty)
    return kelly * (1.0 - penalty)
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_portfolio_corr.py -v
```
Expected: all pass

- [ ] **Step 5: Wire into `_auto_place_trades` in `main.py`**

After the `portfolio_kelly_fraction` call (~line 2721), add:

```python
from portfolio_corr import corr_adjusted_kelly as _corr_kelly

_open_pos = [
    {"city": t.get("city", ""), "kelly": t.get("kelly", 0.0),
     "target_date": t.get("target_date", "")}
    for t in _current_paper_positions
]
adj_kelly = _corr_kelly(city, adj_kelly, _open_pos, target_date_str)
```

- [ ] **Step 6: Commit**

```bash
git add portfolio_corr.py tests/test_portfolio_corr.py main.py
git commit -m "feat(sizing): correlation-aware Kelly reduces same-day correlated city exposure"
```

---

## Phase 5: Condition-Type Calibration + Per-Type Blend Weights

**Prerequisite:** 100+ settled predictions per condition type. Check:
```bash
python -c "
import sqlite3
con = sqlite3.connect('data/predictions.db')
for r in con.execute('SELECT condition_type, count(*) FROM predictions WHERE settled_yes IS NOT NULL GROUP BY condition_type'):
    print(r)
"
```

**What this phase does (two parts):**
1. **Reporting** — `run_backtest` breaks down Brier per condition type so you can see where the model struggles
2. **Separate weights** — `calibration.py` trains separate `ensemble`/`nws`/`climatology` blend weights per condition type, stored in `data/condition_weights.json`

**Files:**
- Modify: `backtest.py` (add `brier_by_condition` to result)
- Modify: `calibration.py` (add `calibrate_condition_weights`)
- Modify: `weather_markets.py` (`_blend_weights` loads condition-type weights)
- Modify: `main.py` (`cmd_backtest` displays breakdown; `cmd_calibrate` trains condition weights)
- Test: `tests/test_calibration.py` (append)

---

### Task 5.1: Brier breakdown in backtest

- [ ] **Step 1: Write the failing test**

```python
# Append to tests/test_calibration.py

def test_run_backtest_reports_per_condition_type(monkeypatch):
    """run_backtest result includes brier_by_condition dict."""
    from unittest.mock import MagicMock
    import backtest

    markets = [
        {"ticker": "KXHIGHNY-26MAY01-T70", "result": "yes", "title": "NYC high > 70°F"},
        {"ticker": "KXHIGHNY-26MAY01-B67.5", "result": "no", "title": "NYC high 67-68°F"},
    ]
    monkeypatch.setattr("backtest._fetch_settled_markets", lambda *a, **kw: markets)
    monkeypatch.setattr("weather_markets.enrich_with_forecast", lambda m: {
        **m, "_city": "NYC",
        "_date": __import__("datetime").date(2026, 5, 1),
        "_lat": 40.77, "_lon": -73.96, "_tz": "America/New_York",
    })
    monkeypatch.setattr("backtest.fetch_archive_temps", lambda *a, **kw: [70.0] * 20)

    result = backtest.run_backtest(MagicMock(), days=30)
    assert "brier_by_condition" in result
    assert isinstance(result["brier_by_condition"], dict)
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_calibration.py::test_run_backtest_reports_per_condition_type -v
```
Expected: FAIL — `brier_by_condition` not in result keys

- [ ] **Step 3: Add to `run_backtest` in `backtest.py`**

In the main scoring loop, accumulate:
```python
_cond_acc: dict[str, list[float]] = {}
# inside loop, after computing sq_err:
_ctype = condition.get("type", "unknown")
_cond_acc.setdefault(_ctype, []).append(sq_err)
```

At end of result dict:
```python
result["brier_by_condition"] = {
    ctype: {"brier": round(sum(errs) / len(errs), 4), "n": len(errs)}
    for ctype, errs in _cond_acc.items()
}
```

- [ ] **Step 4: Add per-type breakdown display to `cmd_backtest` in `main.py`**

After existing Brier printout:
```python
if "brier_by_condition" in result:
    print(dim("\n  Brier by condition type:"))
    for ctype, stats in sorted(result["brier_by_condition"].items()):
        n, b = stats["n"], stats["brier"]
        flag = " ← target <0.20" if b >= 0.20 else " ✓"
        print(f"    {ctype:<14} n={n:<5} Brier={b:.4f}{flag}")
```

- [ ] **Step 5: Commit**

```bash
git add backtest.py main.py tests/test_calibration.py
git commit -m "feat(calibration): Brier breakdown per condition type in backtest output"
```

---

### Task 5.2: Separate blend weights per condition type

- [ ] **Step 1: Write the failing test**

```python
# Append to tests/test_calibration.py

def test_calibrate_condition_weights_returns_per_type_dict():
    """calibrate_condition_weights returns dict keyed by condition type."""
    import random, sqlite3, tempfile, os
    from calibration import calibrate_condition_weights

    random.seed(0)
    with tempfile.TemporaryDirectory() as d:
        db = os.path.join(d, "predictions.db")
        con = sqlite3.connect(db)
        con.executescript("""
            CREATE TABLE predictions (
                ticker TEXT, condition_type TEXT,
                ensemble_prob REAL, clim_prob REAL, nws_prob REAL
            );
            CREATE TABLE outcomes (ticker TEXT, settled_yes INTEGER);
        """)
        for ctype in ("above", "below", "between"):
            for i in range(120):
                t = f"{ctype}-{i}"
                ep = random.uniform(0.3, 0.8)
                cp = random.uniform(0.3, 0.7)
                np_ = random.uniform(0.3, 0.7)
                y = random.randint(0, 1)
                con.execute(
                    "INSERT INTO predictions VALUES (?,?,?,?,?)",
                    (t, ctype, ep, cp, np_),
                )
                con.execute("INSERT INTO outcomes VALUES (?,?)", (t, y))
        con.commit()
        con.close()

        weights = calibrate_condition_weights(db, min_samples=100)

    assert "above" in weights
    assert "below" in weights
    for w in weights.values():
        assert "ensemble" in w
        assert abs(sum(w.values()) - 1.0) < 0.01, "weights must sum to 1"
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_calibration.py::test_calibrate_condition_weights_returns_per_type_dict -v
```
Expected: `ImportError: cannot import name 'calibrate_condition_weights'`

- [ ] **Step 3: Add `calibrate_condition_weights` to `calibration.py`**

The existing grid-search helper is `_best_weights(rows)` (already in `calibration.py`), which takes
`list[tuple[float, float, float, int]]` — (ensemble_prob, clim_prob, nws_prob, settled_yes).
The DB query must select these three source columns and `settled_yes` to build that tuple list.

```python
def calibrate_condition_weights(
    db_path: str | Path,
    min_samples: int = 100,
) -> dict[str, dict[str, float]]:
    """
    For each condition type with enough data, find the source blend weights
    (ensemble, climatology, nws) that minimise historical Brier score.

    Uses the same _best_weights grid-search as calibrate_seasonal_weights but
    groups by condition_type instead of season.

    Returns: {condition_type: {"ensemble": w1, "climatology": w2, "nws": w3}}
    """
    db_path = Path(db_path)
    with sqlite3.connect(str(db_path)) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            """
            SELECT p.condition_type,
                   p.ensemble_prob, p.clim_prob, p.nws_prob,
                   o.settled_yes
            FROM predictions p
            JOIN outcomes o ON p.ticker = o.ticker
            WHERE p.condition_type IS NOT NULL
              AND p.ensemble_prob IS NOT NULL
              AND p.nws_prob IS NOT NULL
              AND p.clim_prob IS NOT NULL
              AND o.settled_yes IS NOT NULL
            """
        ).fetchall()

    by_type: dict[str, list[tuple[float, float, float, int]]] = {}
    for r in rows:
        ct = r["condition_type"]
        by_type.setdefault(ct, []).append(
            (r["ensemble_prob"], r["clim_prob"], r["nws_prob"], r["settled_yes"])
        )

    result: dict[str, dict[str, float]] = {}
    for ctype, tuples in by_type.items():
        if len(tuples) < min_samples:
            _log.info(
                "calibrate_condition_weights: %s has %d rows (need %d) — skipping",
                ctype, len(tuples), min_samples,
            )
            continue
        result[ctype] = _best_weights(tuples)   # reuses existing grid-search helper

    return result
```

- [ ] **Step 4: Wire into `cmd_calibrate` in `main.py`**

After existing seasonal calibration:
```python
from calibration import calibrate_condition_weights

cond_weights = calibrate_condition_weights(db_path, min_samples=100)
if cond_weights:
    cw_path = data_dir / "condition_weights.json"
    cw_path.write_text(json.dumps(cond_weights, indent=2))
    print(green(f"  Condition weights trained for: {', '.join(sorted(cond_weights))}"))
else:
    print(dim("  Condition weights: need 100+ per type"))
```

- [ ] **Step 5: Load condition weights in `weather_markets.py`**

In the blend weight selection (near `_blend_weights` call, ~line 2183), after city/seasonal weights, add:

```python
# Condition-type weights override seasonal when available
try:
    import json as _jj
    from pathlib import Path as _PP
    _cw_path = _PP(__file__).parent / "data" / "condition_weights.json"
    if _cw_path.exists() and condition:
        _cw = _jj.loads(_cw_path.read_text())
        _ctype = condition.get("type", "")
        if _ctype in _cw and len(_cw[_ctype]) >= 2:
            _ctype_weights = _cw[_ctype]
            _total = sum(_ctype_weights.values())
            if _total > 0:
                w_ens  = _ctype_weights.get("ensemble", w_ens) / _total
                w_clim = _ctype_weights.get("climatology", w_clim) / _total
                w_nws  = _ctype_weights.get("nws", w_nws) / _total
except Exception:
    pass
```

- [ ] **Step 6: Run full suite**

```bash
pytest tests/ -q
```
Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add calibration.py main.py weather_markets.py tests/test_calibration.py
git commit -m "feat(calibration): per-condition-type blend weights trained separately"
```

---

## Phase 7: Market Anomaly Detection

**Why:** A Kalshi market moving >12pp against our model between cron cycles usually means news we haven't seen. Flagging it gives the chance to review and potentially exit a paper position.

**Files:**
- Modify: `cron.py`
- Test: `tests/test_cron_integration.py` (append)

---

### Task 7.1: Anomaly detection

- [ ] **Step 1: Write the failing test**

```python
# Append to tests/test_cron_integration.py

def test_report_anomalies_prints_drifted_markets(capsys):
    """report_anomalies prints ticker and drift for markets >12pp from model."""
    import cron as _cron

    anomalies = [
        {"ticker": "KXHIGHNY-26MAY05-T70", "blended_prob": 0.65, "market_price": 0.82},
    ]
    _cron.report_anomalies(anomalies)
    out = capsys.readouterr().out
    assert "KXHIGHNY" in out
    assert "anomal" in out.lower() or "drift" in out.lower() or "%" in out


def test_check_market_anomalies_filters_by_threshold():
    """check_market_anomalies returns only signals with drift > 0.12."""
    import cron as _cron

    signals = [
        {"ticker": "A", "blended_prob": 0.60, "market_price": 0.75},  # 15pp → flagged
        {"ticker": "B", "blended_prob": 0.60, "market_price": 0.65},  # 5pp  → not flagged
    ]
    flagged = _cron.check_market_anomalies(signals)
    assert len(flagged) == 1
    assert flagged[0]["ticker"] == "A"
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_cron_integration.py -k anomaly -v
```
Expected: FAIL — `AttributeError: module 'cron' has no attribute 'report_anomalies'`

- [ ] **Step 3: Add to `cron.py`**

```python
_ANOMALY_THRESHOLD = 0.12  # pp drift required to flag a market


def check_market_anomalies(signals: list[dict]) -> list[dict]:
    """Return signals where |our_prob − market_price| > _ANOMALY_THRESHOLD."""
    return [
        s for s in signals
        if abs(s.get("blended_prob", 0.5) - s.get("market_price", 0.5))
        > _ANOMALY_THRESHOLD
    ]


def report_anomalies(anomalies: list[dict]) -> None:
    """Print anomaly warnings; no-op when list is empty."""
    if not anomalies:
        return
    print(f"\n⚠️  Market anomalies ({len(anomalies)}) — price moved against model:")
    for a in anomalies:
        ticker = a.get("ticker", "?")
        our = a.get("blended_prob", 0.0)
        mkt = a.get("market_price", 0.0)
        print(f"  {ticker:<35} our={our:.0%}  market={mkt:.0%}  drift={mkt-our:+.0%}")
    _log.warning("Anomalies flagged: %s", [a.get("ticker") for a in anomalies])
```

In main cron loop, after computing signals and before placing trades:
```python
_anomalies = check_market_anomalies(signals)
report_anomalies(_anomalies)
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_cron_integration.py -k anomaly -v && pytest tests/ -q
```
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add cron.py tests/test_cron_integration.py
git commit -m "feat(ops): flag market anomalies when price drifts >12pp from model"
```

---

## Phase 6: Dynamic Obs Weight Learning

**Prerequisite (two steps before learning):**

**Step A — DB migration (do this now, before data accumulates):**
Add `obs_weight_used REAL` and `local_hour INTEGER` columns to `predictions` table in `tracker.py`. Run the migration immediately so these fields start being logged.

**Step B — Log the fields:**
In `analyze_trade` in `weather_markets.py`, after computing `_obs_w` and `_local_hour`, store them on the result dict: `result["obs_weight_used"] = _obs_w` and `result["local_hour"] = _local_hour`. In `log_prediction` in `tracker.py`, write these to the DB.

**Step C — Wait for 500+ trades, then train.**

**Files:**
- Modify: `tracker.py` (migration + logging)
- Create: `obs_weight.py`
- Modify: `weather_markets.py` (replace hardcoded ramp)
- Modify: `main.py` (`cmd_calibrate` trains weights)
- Test: `tests/test_obs_weight.py`

---

### Task 6.0: DB migration (do immediately, before other steps)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_obs_weight.py
import sqlite3, tempfile


def test_predictions_table_has_obs_weight_and_local_hour_columns():
    """predictions table must have obs_weight_used and local_hour columns."""
    import tracker

    with tempfile.TemporaryDirectory() as d:
        db_path = f"{d}/predictions.db"
        tracker.init_db(db_path)
        con = sqlite3.connect(db_path)
        cols = [r[1] for r in con.execute("PRAGMA table_info(predictions)").fetchall()]
        con.close()

    assert "obs_weight_used" in cols, "obs_weight_used column missing from predictions"
    assert "local_hour" in cols, "local_hour column missing from predictions"
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_obs_weight.py::test_predictions_table_has_obs_weight_and_local_hour_columns -v
```
Expected: FAIL — columns missing

- [ ] **Step 3: Add migration to `tracker.py`**

In `init_db` (or the migration block that adds columns), add:
```python
for col, typedef in [
    ("obs_weight_used", "REAL"),
    ("local_hour", "INTEGER"),
]:
    try:
        con.execute(f"ALTER TABLE predictions ADD COLUMN {col} {typedef}")
    except Exception:
        pass  # column already exists
```

- [ ] **Step 4: Run test to verify pass**

```bash
pytest tests/test_obs_weight.py::test_predictions_table_has_obs_weight_and_local_hour_columns -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tracker.py tests/test_obs_weight.py
git commit -m "feat(obs-weight): add obs_weight_used and local_hour columns to predictions"
```

---

### Task 6.1: Learn and apply dynamic obs weights (after 500+ trades)

- [ ] **Step 1: Write the failing tests** (add to `tests/test_obs_weight.py`)

```python
def test_learn_obs_weights_returns_dict():
    import obs_weight, random
    random.seed(42)
    rows = [
        {"city": "NYC", "local_hour": 14, "obs_weight_used": 0.80, "brier": 0.05}
    ] * 60
    weights = obs_weight.learn_obs_weights(rows, min_samples=50)
    assert isinstance(weights, dict)


def test_get_obs_weight_falls_back_to_formula():
    import obs_weight
    # No learned weights — must use formula default
    w = obs_weight.get_obs_weight("NYC", local_hour=14, days_out=0, learned={})
    assert 0.70 <= w <= 0.85  # formula: 0.55 + 14/24 * 0.40 = 0.783


def test_get_obs_weight_uses_learned_when_available():
    import obs_weight
    learned = {("NYC", 2): 0.92}  # bucket 2 = hours 12-17
    w = obs_weight.get_obs_weight("NYC", local_hour=14, days_out=0, learned=learned)
    assert w == 0.92


def test_days_out_nonzero_returns_zero():
    import obs_weight
    w = obs_weight.get_obs_weight("NYC", local_hour=14, days_out=1, learned={})
    assert w == 0.0  # obs not used for future days
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_obs_weight.py -v
```
Expected: `ModuleNotFoundError: No module named 'obs_weight'`

- [ ] **Step 3: Implement `obs_weight.py`**

```python
# obs_weight.py
"""
Learn per-(city, hour_bucket) optimal observation weights from settled history.
Falls back to the hardcoded linear ramp when no learned weights are available.

Hour buckets: 0=00-05h, 1=06-11h, 2=12-17h, 3=18-23h
"""
from __future__ import annotations
import json, statistics
from collections import defaultdict
from pathlib import Path

_WEIGHTS_PATH = Path(__file__).parent / "data" / "obs_weights.json"


def _hour_bucket(local_hour: int) -> int:
    if local_hour <= 5:  return 0
    if local_hour <= 11: return 1
    if local_hour <= 17: return 2
    return 3


def learn_obs_weights(
    rows: list[dict],
    min_samples: int = 50,
) -> dict[tuple[str, int], float]:
    """
    For each (city, hour_bucket), select the obs_weight_used that produced
    the lowest average Brier score historically.

    rows: list of dicts with city, local_hour, obs_weight_used, brier
    Returns: {(city, hour_bucket): best_weight}
    """
    groups: dict[tuple, list[tuple[float, float]]] = defaultdict(list)
    for r in rows:
        city, hour, w, b = (
            r.get("city"), r.get("local_hour"),
            r.get("obs_weight_used"), r.get("brier"),
        )
        if city and hour is not None and w is not None and b is not None:
            groups[(city, _hour_bucket(int(hour)))].append((float(w), float(b)))

    result: dict[tuple, float] = {}
    for key, samples in groups.items():
        if len(samples) < min_samples:
            continue
        bins: dict[float, list[float]] = {}
        for w, b in samples:
            bucket = round(round(w / 0.05) * 0.05, 2)
            bins.setdefault(bucket, []).append(b)
        best_w = min(bins, key=lambda k: statistics.mean(bins[k]))
        result[key] = best_w

    return result


def get_obs_weight(
    city: str,
    local_hour: int,
    days_out: int,
    learned: dict | None = None,
) -> float:
    if days_out > 0:
        return 0.0

    if learned is None:
        try:
            if _WEIGHTS_PATH.exists():
                raw = json.loads(_WEIGHTS_PATH.read_text())
                learned = {(k.split("|")[0], int(k.split("|")[1])): v
                           for k, v in raw.items()}
            else:
                learned = {}
        except Exception:
            learned = {}

    key = (city, _hour_bucket(local_hour))
    if key in learned:
        return float(learned[key])

    return min(0.95, 0.55 + local_hour / 24.0 * 0.40)


def save_obs_weights(weights: dict[tuple, float]) -> None:
    serialisable = {f"{city}|{bucket}": w for (city, bucket), w in weights.items()}
    _WEIGHTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _WEIGHTS_PATH.write_text(json.dumps(serialisable, indent=2))
```

- [ ] **Step 4: Replace hardcoded ramp in `weather_markets.py`**

Find `_obs_w = min(0.95, 0.55 + _local_hour / 24.0 * 0.40)` and replace with:
```python
try:
    from obs_weight import get_obs_weight as _get_obs_w
    _obs_w = _get_obs_w(city, _local_hour, days_out)
except Exception:
    _obs_w = min(0.95, 0.55 + _local_hour / 24.0 * 0.40)
```

- [ ] **Step 5: Wire into `cmd_calibrate`**

```python
from obs_weight import learn_obs_weights, save_obs_weights
obs_rows = [dict(r) for r in con.execute(
    "SELECT city, local_hour, obs_weight_used, "
    "       (our_prob - settled_yes) * (our_prob - settled_yes) AS brier "
    "FROM predictions WHERE settled_yes IS NOT NULL "
    "AND obs_weight_used IS NOT NULL AND local_hour IS NOT NULL"
).fetchall()]
obs_weights = learn_obs_weights(obs_rows, min_samples=50)
if obs_weights:
    save_obs_weights(obs_weights)
    print(green(f"  Obs weights learned for {len(obs_weights)} city/hour buckets"))
else:
    print(dim("  Obs weights: need obs_weight_used + local_hour logged (500+ trades)"))
```

- [ ] **Step 6: Run full suite**

```bash
pytest tests/ -q
```
Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add obs_weight.py tests/test_obs_weight.py weather_markets.py main.py
git commit -m "feat(calibration): dynamic per-city obs weight learned from settled history"
```

---

## Self-review checklist

**Spec coverage:**
- [x] NBM/ensemble CDF — Phase 1 (51-member empirical CDF, not NWS approximation)
- [x] Per-city Platt scaling — Phase 2
- [x] Portfolio correlation Kelly — Phase 3
- [x] Automated daily report — Phase 4 (Slack + SMTP)
- [x] Condition-type calibration — Phase 5 (Brier reporting + separate blend weights)
- [x] Dynamic obs weight — Phase 6 (DB migration first, then learn)
- [x] Market anomaly detection — Phase 7
- [x] Live trading readiness gate — Phase 8

**Corrections applied vs first draft:**
- Phase 1: switched from NWS pseudo-quantiles (wrong) to Open-Meteo 51-member empirical CDF (correct)
- Phase 3: penalty formula documented as intentionally mild; instructions to tighten added
- Phase 5: now trains separate blend weights per condition type, not just reporting
- Phase 6: explicit DB migration as Task 6.0 before any learning steps

**Corrections applied vs second draft (code-reality audit):**
- Phase 1: `_om_get()` → `_om_request("GET", ...).json()` (actual function name); `"daily": member_vars` → `"hourly": "temperature_2m"` (API only returns hourly per member); daily high/low computed as `max/min(hourly_vals)` per member; members 1-indexed (`member01…member51`); test mocks `_om_request` not `_om_get`
- Phase 2: removed `sklearn.linear_model.LogisticRegression` (not in requirements.txt); replaced with `scipy.optimize.minimize` cross-entropy fit (`scipy` already in requirements)
- Phase 5: `_fit_blend_weights(samples)` → `_best_weights(tuples)` (actual helper name); `calibrate_condition_weights` takes `db_path` not `rows` and queries DB directly using the same schema as `calibrate_seasonal_weights`; test creates a real temp SQLite DB instead of passing raw dicts
- Phase 8: `_get_current_drawdown` and `_circuit_breaker_open` don't exist in `main.py` — added as explicit wrapper functions so monkeypatching works; they delegate to `paper.get_max_drawdown_pct()` and `flash_crash_cb.is_open()` respectively

**Data prerequisites clearly gated:**
- Phase 2: 200+ trades/city check command provided
- Phase 5: 100+ trades/condition type check command provided
- Phase 6: 500+ trades + DB migration (Task 6.0 unblocked immediately)

**Type consistency:**
- `get_ensemble_members` → `list[float] | None` throughout
- `ensemble_cdf_prob` → `float`, takes `list[float]` and `dict`
- `train_platt_per_city` → `dict[str, tuple[float, float]]`
- `apply_platt_per_city` → `float`, matches signature
- `corr_adjusted_kelly` → `float`, consistent with existing `portfolio_kelly_fraction`
- `cmd_readiness` → `bool`
