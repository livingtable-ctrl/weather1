# Fix High Early Exit Rate on Paper Trades

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dramatically reduce spurious early exits on paper trades. Two exit code paths run on every cron/watch cycle; both use thresholds that are too tight for normal forecast noise.

**Architecture:**

| Code path | Location | Current trigger | Problem |
|---|---|---|---|
| `check_model_exits` | `paper.py:1316` | `abs(net_edge) < 0.03` (edge_gone) | 3% is normal forecast variance — exits winning trades |
| `check_model_exits` | `paper.py:1312` | `net_edge < -0.05` (model_flipped) | ±5% is noise — not a real flip |
| `_check_early_exits` | `main.py:2334` | `probability_shift > 0.15` (15pp) | Reasonable but no minimum hold time — new trades exit within hours |

**Fixes:**
1. Raise `edge_gone` to `< -0.05` (only exit when edge is meaningfully negative, not just weak)
2. Raise `model_flipped` to `< -0.10` / `> 0.10` (10% net edge required to confirm a flip)
3. Add a **12-hour minimum hold time** to `check_model_exits` — no exits before 12h after entry
4. Add the same **12-hour minimum hold time** to `_check_early_exits`

**Tech Stack:** Python, `paper.py`, `main.py`, `tests/test_early_exits.py` (new)

---

## Root Cause Summary

| Bug | File | Location | Cause |
|---|---|---|---|
| Too many `edge_gone` exits | `paper.py` | Line 1316 | `abs(net_edge) < 0.03` fires on trivial model noise |
| Too many `model_flipped` exits | `paper.py` | Line 1312 | ±5% net edge fires on normal short-term forecast jitter |
| Exits within hours of entry | `main.py` | Line 2334 | No minimum hold time — trade placed at noon can exit at 4pm |
| Same for `check_model_exits` | `paper.py` | Line 1302 | No hold-time guard at all |

---

## Task 1: Tighten thresholds and add minimum hold time in `check_model_exits`

**Files:**
- Modify: `paper.py` ~lines 1309–1316
- Create: `tests/test_early_exits.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_early_exits.py`:

```python
"""Tests for early exit threshold and hold-time guards."""
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch


def _make_trade(entered_hours_ago: float, side: str = "yes") -> dict:
    entered_at = (datetime.now(timezone.utc) - timedelta(hours=entered_hours_ago)).isoformat()
    return {
        "id": 1, "ticker": "KXWT-24-T50-B3", "side": side,
        "entry_prob": 0.65, "quantity": 10, "cost": 3.0,
        "entered_at": entered_at,
    }


class TestCheckModelExitsThresholds:
    def test_edge_gone_threshold_is_negative(self):
        """check_model_exits must NOT exit a trade whose edge merely dropped from 8% to 2%.
        Only exit when edge is meaningfully negative (< -5%)."""
        from paper import check_model_exits

        fake_trade = _make_trade(entered_hours_ago=24)  # well past hold time

        mock_analysis = {
            "net_edge": 0.02,         # weak but still positive — should NOT exit
            "edge": 0.02,
            "recommended_side": "yes",
        }
        mock_client = MagicMock()
        mock_client.get_market.return_value = {"ticker": "KXWT-24-T50-B3"}

        with patch("paper.get_open_trades", return_value=[fake_trade]), \
             patch("weather_markets.enrich_with_forecast", return_value={}), \
             patch("weather_markets.analyze_trade", return_value=mock_analysis):
            recs = check_model_exits(mock_client)

        assert len(recs) == 0, (
            "Should not exit a trade with net_edge=+2%; only exit when edge is negative"
        )

    def test_model_flipped_requires_10pct_net_edge(self):
        """check_model_exits model_flipped must require net_edge < -0.10 (not -0.05)."""
        from paper import check_model_exits

        fake_trade = _make_trade(entered_hours_ago=24)

        mock_analysis = {
            "net_edge": -0.07,   # between -5% and -10% — should NOT trigger flip
            "edge": -0.07,
            "recommended_side": "no",
        }
        mock_client = MagicMock()
        mock_client.get_market.return_value = {"ticker": "KXWT-24-T50-B3"}

        with patch("paper.get_open_trades", return_value=[fake_trade]), \
             patch("weather_markets.enrich_with_forecast", return_value={}), \
             patch("weather_markets.analyze_trade", return_value=mock_analysis):
            recs = check_model_exits(mock_client)

        assert len(recs) == 0, (
            "net_edge=-7% should NOT trigger model_flipped exit (threshold is -10%)"
        )

    def test_minimum_hold_time_prevents_early_exit(self):
        """check_model_exits must not exit a trade entered less than 12 hours ago."""
        from paper import check_model_exits

        new_trade = _make_trade(entered_hours_ago=6)  # only 6h old

        mock_analysis = {
            "net_edge": -0.20,  # clearly negative — would exit if not for hold time
            "edge": -0.20,
            "recommended_side": "no",
        }
        mock_client = MagicMock()
        mock_client.get_market.return_value = {"ticker": "KXWT-24-T50-B3"}

        with patch("paper.get_open_trades", return_value=[new_trade]), \
             patch("weather_markets.enrich_with_forecast", return_value={}), \
             patch("weather_markets.analyze_trade", return_value=mock_analysis):
            recs = check_model_exits(mock_client)

        assert len(recs) == 0, (
            "Trade entered 6h ago must not be exited — minimum hold time is 12h"
        )
```

- [ ] **Step 2: Run tests to verify they fail**

```
python -m pytest tests/test_early_exits.py -v
```

Expected: FAIL — current thresholds are looser than what the tests require.

- [ ] **Step 3: Update `check_model_exits` in `paper.py`**

Find (around lines 1309–1316):
```python
            flipped = (held_side == "yes" and net_edge < -0.05) or (
                held_side == "no" and net_edge > 0.05
            )
            # Edge gone: less than 3% after fees — no longer worth holding
            edge_gone = abs(net_edge) < 0.03
```

Replace with:
```python
            # Model flipped: requires a meaningful reversal (10pp threshold)
            flipped = (held_side == "yes" and net_edge < -0.10) or (
                held_side == "no" and net_edge > 0.10
            )
            # Edge gone: only exit when edge is meaningfully negative (not just weak)
            edge_gone = net_edge < -0.05

            # Minimum hold time: do not exit positions entered within the last 12 hours.
            # New forecast data stabilises after 6–12h; early exits on noisy first-cycle
            # updates are almost always spurious.
            from datetime import datetime, timezone as _tz, timedelta as _td
            entered_at_str = t.get("entered_at", "")
            if entered_at_str:
                try:
                    entered_dt = datetime.fromisoformat(
                        entered_at_str.replace("Z", "+00:00")
                    )
                    if entered_dt.tzinfo is None:
                        entered_dt = entered_dt.replace(tzinfo=_tz.utc)
                    hours_held = (datetime.now(_tz.utc) - entered_dt).total_seconds() / 3600
                    if hours_held < 12:
                        continue  # too soon — let the position breathe
                except (ValueError, TypeError):
                    pass
```

- [ ] **Step 4: Run tests to verify they pass**

```
python -m pytest tests/test_early_exits.py -v
```

Expected: PASS.

---

## Task 2: Add minimum hold time to `_check_early_exits` in `main.py`

**Files:**
- Modify: `main.py` ~line 2334
- Test: `tests/test_early_exits.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_early_exits.py`:

```python
class TestCheckEarlyExitsHoldTime:
    def test_new_trade_not_exited_by_probability_shift(self):
        """_check_early_exits must not exit a trade entered less than 12 hours ago."""
        import main

        new_trade = _make_trade(entered_hours_ago=4)

        mock_market = {"ticker": "KXWT-24-T50-B3", "yes_bid": 30}
        mock_analysis = {"forecast_prob": 0.30, "net_edge": -0.20}
        mock_client = MagicMock()
        mock_client.get_market.return_value = mock_market

        with patch("main.get_weather_markets", return_value=[mock_market]), \
             patch("main.enrich_with_forecast", return_value=mock_market), \
             patch("main.analyze_trade", return_value=mock_analysis), \
             patch("main.get_open_trades", return_value=[new_trade]):
            closed = main._check_early_exits(mock_client)

        assert closed == 0, (
            "Trade entered 4h ago must not be exited — minimum hold time is 12h"
        )
```

- [ ] **Step 2: Run test to verify it fails**

```
python -m pytest tests/test_early_exits.py::TestCheckEarlyExitsHoldTime -v
```

Expected: FAIL.

- [ ] **Step 3: Add hold-time guard to `_check_early_exits` in `main.py`**

Find (around line 2329):
```python
            if shift > 0.15:
```

Replace with:
```python
            # Minimum hold time — skip exits for trades placed within 12 hours
            entered_at_str = trade.get("entered_at", "")
            if entered_at_str:
                try:
                    entered_dt = datetime.fromisoformat(
                        entered_at_str.replace("Z", "+00:00")
                    )
                    if entered_dt.tzinfo is None:
                        entered_dt = entered_dt.replace(tzinfo=UTC)
                    hours_held = (datetime.now(UTC) - entered_dt).total_seconds() / 3600
                    if hours_held < 12:
                        continue
                except (ValueError, TypeError):
                    pass

            if shift > 0.15:
```

- [ ] **Step 4: Run all early-exit tests**

```
python -m pytest tests/test_early_exits.py -v
```

Expected: PASS — 4 tests green.

- [ ] **Step 5: Run full suite**

```
python -m pytest tests/ -q --tb=short
```

Expected: all prior tests still pass, 4 new tests pass.

- [ ] **Step 6: Commit**

```bash
git add paper.py main.py tests/test_early_exits.py
git commit -m "fix: raise early-exit thresholds and add 12h minimum hold time to prevent spurious exits"
```

---

## Self-Review

**Spec coverage:**
- ✅ `edge_gone` threshold tightened → Task 1 Step 3 (`net_edge < -0.05` not `abs < 0.03`)
- ✅ `model_flipped` threshold raised → Task 1 Step 3 (±10% not ±5%)
- ✅ 12h hold in `check_model_exits` → Task 1 Step 3
- ✅ 12h hold in `_check_early_exits` → Task 2 Step 3

**Placeholder scan:** None found.

**Type consistency:** `datetime`, `timedelta` already imported in both files.
