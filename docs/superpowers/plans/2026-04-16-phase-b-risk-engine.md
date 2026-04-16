# Phase B: Risk Engine Implementation Plan

> **Status: ✅ COMPLETE — 2026-04-16** — All 3 tasks implemented, reviewed, and committed on branch `claude/jolly-robinson`.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Add three risk calibration improvements: step-function drawdown-tiered Kelly reduction, per-market flash crash circuit breaker, and confidence-tiered edge thresholds.

**Architecture:** All three are independent and can be done in any order. Drawdown tiers modify `paper.py`'s `drawdown_scaling_factor()`. Flash crash CB adds a new class to `circuit_breaker.py` and wires into `main.py`'s `_validate_trade_opportunity`. Confidence tiers add a function to `utils.py` and modify the edge threshold check in `_validate_trade_opportunity`.

**Tech Stack:** Python 3.12, existing `paper.py`, `circuit_breaker.py`, `utils.py`, `main.py`, pytest

---

## Task 1: Drawdown-Tiered Kelly Step Reduction

**Files:**
- Modify: `paper.py` (update `drawdown_scaling_factor()`)
- Create: `tests/test_drawdown_tiers.py`

**Current behavior:** Linear ramp from 0.0 (at 50% drawdown) to 1.0 (at 0% drawdown). Smooth but doesn't explicitly enforce the research-specified protection levels.

**New behavior:** Step function matching the research spec:

| Peak Recovery | Drawdown | Kelly Multiplier |
|--------------|---------|-----------------|
| ≥ 90% | 0–10% | 1.00 (full half-Kelly) |
| 80–90% | 10–20% | 0.50 |
| 60–80% | 20–40% | 0.20 (survival mode) |
| < 60% | > 40% | 0.00 (paused) |

- [x] **Step 1: Write the failing tests**

Create `tests/test_drawdown_tiers.py`:

```python
"""Tests for step-function drawdown-tiered Kelly reduction."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestDrawdownScalingFactor:
    def _patch_balances(self, balance: float, peak: float):
        """Return a context manager patching get_balance and get_peak_balance."""
        import paper
        from unittest.mock import patch as _patch
        return (
            _patch.object(paper, "get_balance", return_value=balance),
            _patch.object(paper, "get_peak_balance", return_value=peak),
        )

    def test_no_drawdown_full_kelly(self):
        """At 100% recovery (no drawdown), scaling factor = 1.0."""
        import paper
        with patch.object(paper, "get_balance", return_value=1000.0), \
             patch.object(paper, "get_peak_balance", return_value=1000.0):
            assert paper.drawdown_scaling_factor() == pytest.approx(1.0)

    def test_5pct_drawdown_full_kelly(self):
        """5% drawdown (95% recovery) still gets full Kelly (tier 1)."""
        import paper
        with patch.object(paper, "get_balance", return_value=950.0), \
             patch.object(paper, "get_peak_balance", return_value=1000.0):
            factor = paper.drawdown_scaling_factor()
            assert factor == pytest.approx(1.0)

    def test_10pct_drawdown_half_kelly(self):
        """10% drawdown (90% recovery) = tier boundary → 0.50."""
        import paper
        with patch.object(paper, "get_balance", return_value=900.0), \
             patch.object(paper, "get_peak_balance", return_value=1000.0):
            factor = paper.drawdown_scaling_factor()
            assert factor == pytest.approx(0.50)

    def test_15pct_drawdown_half_kelly(self):
        """15% drawdown (85% recovery) is in tier 2 → 0.50."""
        import paper
        with patch.object(paper, "get_balance", return_value=850.0), \
             patch.object(paper, "get_peak_balance", return_value=1000.0):
            factor = paper.drawdown_scaling_factor()
            assert factor == pytest.approx(0.50)

    def test_20pct_drawdown_survival_mode(self):
        """20% drawdown (80% recovery) enters survival mode → 0.20."""
        import paper
        with patch.object(paper, "get_balance", return_value=800.0), \
             patch.object(paper, "get_peak_balance", return_value=1000.0):
            factor = paper.drawdown_scaling_factor()
            assert factor == pytest.approx(0.20)

    def test_35pct_drawdown_survival_mode(self):
        """35% drawdown (65% recovery) still in survival mode → 0.20."""
        import paper
        with patch.object(paper, "get_balance", return_value=650.0), \
             patch.object(paper, "get_peak_balance", return_value=1000.0):
            factor = paper.drawdown_scaling_factor()
            assert factor == pytest.approx(0.20)

    def test_40pct_drawdown_paused(self):
        """40%+ drawdown (≤ 60% recovery) → paused, factor = 0.0."""
        import paper
        with patch.object(paper, "get_balance", return_value=600.0), \
             patch.object(paper, "get_peak_balance", return_value=1000.0):
            factor = paper.drawdown_scaling_factor()
            assert factor == pytest.approx(0.0)

    def test_50pct_drawdown_paused(self):
        """50% drawdown → still paused."""
        import paper
        with patch.object(paper, "get_balance", return_value=500.0), \
             patch.object(paper, "get_peak_balance", return_value=1000.0):
            factor = paper.drawdown_scaling_factor()
            assert factor == pytest.approx(0.0)

    def test_zero_peak_balance_returns_one(self):
        """Guard: peak balance = 0 returns 1.0 (no history)."""
        import paper
        with patch.object(paper, "get_balance", return_value=1000.0), \
             patch.object(paper, "get_peak_balance", return_value=0.0):
            assert paper.drawdown_scaling_factor() == pytest.approx(1.0)
```

- [x] **Step 2: Run tests to verify some fail**

```
cd "C:/Users/thesa/claude kalshi"
python -m pytest tests/test_drawdown_tiers.py -v
```

Expected: the tier-specific tests (10%, 20%, 40%) fail with wrong values from current linear ramp

- [x] **Step 3: Update `drawdown_scaling_factor()` in `paper.py`**

Find `drawdown_scaling_factor()` in `paper.py` (around line 290) and replace the body:

```python
def drawdown_scaling_factor() -> float:
    """
    Return a 0.0–1.0 Kelly multiplier based on drawdown from peak (high-water mark).

    Step tiers (research-backed):
      < 60% of peak  → 0.00  (paused — > 40% drawdown)
      60–80% of peak → 0.20  (survival mode — 20–40% drawdown)
      80–90% of peak → 0.50  (reduced — 10–20% drawdown)
      ≥ 90% of peak  → 1.00  (normal — < 10% drawdown)
    """
    peak = get_peak_balance()
    if peak <= 0:
        return 1.0
    recovery = get_balance() / peak

    if recovery < 0.60:
        return 0.0
    if recovery < 0.80:
        return 0.20
    if recovery < 0.90:
        return 0.50
    return 1.0
```

- [x] **Step 4: Run tests to verify they all pass**

```
python -m pytest tests/test_drawdown_tiers.py -v
```

Expected: 9 tests PASSED

- [x] **Step 5: Run existing drawdown-related tests to verify no regression**

```
python -m pytest tests/test_risk_control.py tests/test_paper.py -v
```

Expected: all pass

- [x] **Step 6: Commit**

```bash
git add paper.py tests/test_drawdown_tiers.py
git commit -m "feat(risk): replace linear drawdown ramp with step-function tiers (0%→1.0x, 10%→0.5x, 20%→0.2x, 40%→paused)"
```

---

## Task 2: Per-Market Flash Crash Circuit Breaker

**Files:**
- Modify: `circuit_breaker.py` (add `FlashCrashCB` class)
- Modify: `main.py` (`_validate_trade_opportunity` calls the CB)
- Create: `tests/test_flash_crash_cb.py`

**What it does:** Tracks price history per ticker in an in-memory dict (cleared on restart). If any ticker's price moves more than `threshold_pct` (default 20%) within `window_seconds` (default 300 = 5 min), that ticker goes into `cooldown_seconds` (default 600 = 10 min). During cooldown, `_validate_trade_opportunity` rejects the ticker with reason `"flash crash cooldown"`.

This is separate from the existing data-source circuit breakers (which trip on API failures). This one trips on market price behavior.

- [x] **Step 1: Write the failing tests**

Create `tests/test_flash_crash_cb.py`:

```python
"""Tests for per-market flash crash circuit breaker."""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestFlashCrashCB:
    def setup_method(self):
        from circuit_breaker import FlashCrashCB
        self.cb = FlashCrashCB(
            threshold_pct=0.20,
            window_seconds=300,
            cooldown_seconds=600,
        )

    def test_no_crash_on_first_observation(self):
        """First price observation never triggers a crash."""
        assert self.cb.check("TICKER-A", 0.50) is False

    def test_no_crash_on_small_move(self):
        """A 10% move does NOT trigger a crash (threshold=20%)."""
        self.cb.check("TICKER-A", 0.50)
        result = self.cb.check("TICKER-A", 0.55)
        assert result is False

    def test_crash_on_large_move(self):
        """A 25% move DOES trigger the crash circuit breaker."""
        self.cb.check("TICKER-A", 0.60)
        result = self.cb.check("TICKER-A", 0.45)  # -25% from 0.60
        assert result is True

    def test_cooldown_prevents_trading(self):
        """After a crash triggers, is_in_cooldown returns True."""
        self.cb.check("TICKER-B", 0.60)
        self.cb.check("TICKER-B", 0.40)  # -33% → triggers crash
        assert self.cb.is_in_cooldown("TICKER-B") is True

    def test_different_tickers_independent(self):
        """Crash on TICKER-C does not affect TICKER-D."""
        self.cb.check("TICKER-C", 0.80)
        self.cb.check("TICKER-C", 0.40)  # triggers crash on C
        assert self.cb.is_in_cooldown("TICKER-C") is True
        assert self.cb.is_in_cooldown("TICKER-D") is False

    def test_no_cooldown_on_clean_ticker(self):
        """Ticker with no observations or small moves is not in cooldown."""
        assert self.cb.is_in_cooldown("BRAND-NEW-TICKER") is False

    def test_cooldown_expires(self):
        """After cooldown_seconds, is_in_cooldown returns False."""
        cb = FlashCrashCB(threshold_pct=0.20, window_seconds=1, cooldown_seconds=1)
        cb.check("TICKER-E", 0.80)
        cb.check("TICKER-E", 0.40)  # triggers
        assert cb.is_in_cooldown("TICKER-E") is True
        time.sleep(1.1)
        assert cb.is_in_cooldown("TICKER-E") is False

    def test_upward_spike_also_triggers(self):
        """A large upward move (e.g. 0.30 → 0.70 = +133%) also triggers."""
        self.cb.check("TICKER-F", 0.30)
        result = self.cb.check("TICKER-F", 0.70)
        assert result is True
```

- [x] **Step 2: Run tests to verify they fail**

```
python -m pytest tests/test_flash_crash_cb.py -v
```

Expected: `ImportError: cannot import name 'FlashCrashCB'`

- [x] **Step 3: Add `FlashCrashCB` to `circuit_breaker.py`**

Read `circuit_breaker.py` first. Then add at the bottom of the file:

```python
# ── Flash Crash Circuit Breaker ───────────────────────────────────────────────


class FlashCrashCB:
    """
    Per-market flash crash detection.
    If a market's price moves more than threshold_pct within window_seconds,
    the market enters cooldown and all trades for that ticker are blocked.

    Uses in-memory storage — resets on restart (intentional: stale flash
    crashes should not persist across restarts).
    """

    def __init__(
        self,
        threshold_pct: float = 0.20,
        window_seconds: int = 300,
        cooldown_seconds: int = 600,
    ) -> None:
        self.threshold_pct = threshold_pct
        self.window_seconds = window_seconds
        self.cooldown_seconds = cooldown_seconds
        # {ticker: deque of (timestamp, price)}
        self._history: dict[str, list[tuple[float, float]]] = {}
        # {ticker: cooldown_until_timestamp}
        self._cooldowns: dict[str, float] = {}

    def check(self, ticker: str, current_price: float) -> bool:
        """
        Record a price observation and check if a crash has occurred.

        Returns:
            True if this observation triggered a crash (market entering cooldown)
            False otherwise
        """
        import time as _time

        now = _time.time()

        if ticker not in self._history:
            self._history[ticker] = []

        # Prune old observations outside the window
        window_start = now - self.window_seconds
        self._history[ticker] = [
            (ts, p) for ts, p in self._history[ticker] if ts >= window_start
        ]

        # Record current observation
        self._history[ticker].append((now, current_price))

        # Check for crash: compare current price to oldest price in window
        if len(self._history[ticker]) < 2:
            return False

        oldest_price = self._history[ticker][0][1]
        if oldest_price <= 0:
            return False

        pct_change = abs(current_price - oldest_price) / oldest_price
        if pct_change >= self.threshold_pct:
            # Trigger cooldown
            self._cooldowns[ticker] = now + self.cooldown_seconds
            import logging
            logging.getLogger(__name__).warning(
                "FLASH CRASH CB: %s — price moved %.1f%% in %ds window "
                "(%.2f → %.2f). Cooldown %ds.",
                ticker, pct_change * 100, self.window_seconds,
                oldest_price, current_price, self.cooldown_seconds,
            )
            return True

        return False

    def is_in_cooldown(self, ticker: str) -> bool:
        """Return True if the ticker is currently in flash-crash cooldown."""
        import time as _time

        cooldown_until = self._cooldowns.get(ticker, 0)
        return _time.time() < cooldown_until


# Module-level singleton — used by _validate_trade_opportunity
flash_crash_cb = FlashCrashCB()
```

- [x] **Step 4: Run tests to verify they pass**

```
python -m pytest tests/test_flash_crash_cb.py -v
```

Expected: 8 tests PASSED

- [x] **Step 5: Wire into `_validate_trade_opportunity` in `main.py`**

In `main.py`, find `_validate_trade_opportunity` (search for `def _validate_trade_opportunity`). Add a flash crash check after the existing health check:

```python
# Flash crash check — per-market price-movement circuit breaker
try:
    from circuit_breaker import flash_crash_cb
    yes_bid = opp.get("yes_bid", 0) or 0
    yes_ask = opp.get("yes_ask", 0) or 0
    mid = (yes_bid + yes_ask) / 2 if yes_ask > 0 else yes_bid
    if mid > 0:
        flash_crash_cb.check(opp["ticker"], float(mid))
    if flash_crash_cb.is_in_cooldown(opp["ticker"]):
        return "flash crash cooldown"
except Exception:
    pass
```

- [x] **Step 6: Run full test suite**

```
python -m pytest tests/test_flash_crash_cb.py tests/test_trade_validation.py -v
```

Expected: all pass

- [x] **Step 7: Commit**

```bash
git add circuit_breaker.py tests/test_flash_crash_cb.py main.py
git commit -m "feat(risk): add FlashCrashCB — per-market price-movement circuit breaker; wire into _validate_trade_opportunity"
```

---

## Task 3: Confidence-Tiered Edge Thresholds

**Files:**
- Modify: `utils.py` (add `get_min_edge_for_confidence()`)
- Modify: `main.py` (`_validate_trade_opportunity` uses tiered threshold)
- Create: `tests/test_confidence_tiers.py`

**What it does:** Replace the single `MIN_EDGE` threshold with three tiers based on ensemble agreement. When the ensemble spread is wide (models disagree), we demand higher edge before entering. When models strongly agree, we'll accept a lower edge.

**Tier criteria** (spread = standard deviation of ensemble member probabilities, or ensemble σ of temperature forecasts):

| Tier | Ensemble Spread | Min Edge |
|------|----------------|---------|
| HIGH | spread ≤ 5% probability units | 5% (paper) / 8% (live) |
| MODERATE | spread 5–15% probability units | 7% (paper) / 10% (live) |
| LOW | spread > 15% probability units | 10% (paper) / 15% (live) |

- [x] **Step 1: Write the failing tests**

Create `tests/test_confidence_tiers.py`:

```python
"""Tests for confidence-tiered edge thresholds."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestGetMinEdgeForConfidence:
    def test_high_confidence_low_spread(self):
        """Ensemble spread ≤ 5% → HIGH confidence → min edge 5% for paper."""
        from utils import get_min_edge_for_confidence

        edge = get_min_edge_for_confidence(spread=0.04, is_live=False)
        assert edge == pytest.approx(0.05)

    def test_moderate_confidence_medium_spread(self):
        """Ensemble spread 10% → MODERATE → min edge 7% for paper."""
        from utils import get_min_edge_for_confidence

        edge = get_min_edge_for_confidence(spread=0.10, is_live=False)
        assert edge == pytest.approx(0.07)

    def test_low_confidence_wide_spread(self):
        """Ensemble spread 20% → LOW → min edge 10% for paper."""
        from utils import get_min_edge_for_confidence

        edge = get_min_edge_for_confidence(spread=0.20, is_live=False)
        assert edge == pytest.approx(0.10)

    def test_live_thresholds_higher(self):
        """Live thresholds are higher than paper for each tier."""
        from utils import get_min_edge_for_confidence

        assert get_min_edge_for_confidence(0.04, is_live=True) > get_min_edge_for_confidence(0.04, is_live=False)
        assert get_min_edge_for_confidence(0.10, is_live=True) > get_min_edge_for_confidence(0.10, is_live=False)
        assert get_min_edge_for_confidence(0.20, is_live=True) > get_min_edge_for_confidence(0.20, is_live=False)

    def test_zero_spread_is_high(self):
        """Zero spread (perfect consensus) → HIGH tier."""
        from utils import get_min_edge_for_confidence

        assert get_min_edge_for_confidence(0.0, is_live=False) == pytest.approx(0.05)

    def test_classify_confidence_returns_string(self):
        """classify_confidence_tier returns 'HIGH', 'MODERATE', or 'LOW'."""
        from utils import classify_confidence_tier

        assert classify_confidence_tier(0.04) == "HIGH"
        assert classify_confidence_tier(0.10) == "MODERATE"
        assert classify_confidence_tier(0.20) == "LOW"
        assert classify_confidence_tier(0.05) == "MODERATE"  # boundary → MODERATE
```

- [x] **Step 2: Run tests to verify they fail**

```
python -m pytest tests/test_confidence_tiers.py -v
```

Expected: `ImportError: cannot import name 'get_min_edge_for_confidence'`

- [x] **Step 3: Add functions to `utils.py`**

Add to `utils.py` after the existing `MIN_EDGE`/`PAPER_MIN_EDGE` constants:

```python
# Confidence-tiered edge thresholds — spread is std dev of ensemble probabilities
# HIGH: models strongly agree (spread ≤ 5%) → lower edge required
# MODERATE: normal uncertainty (5–15%) → standard edge
# LOW: models disagree (> 15%) → higher edge required before entering
_EDGE_TIERS: dict[str, dict[str, float]] = {
    "HIGH":     {"paper": 0.05, "live": 0.08},
    "MODERATE": {"paper": 0.07, "live": 0.10},
    "LOW":      {"paper": 0.10, "live": 0.15},
}


def classify_confidence_tier(spread: float) -> str:
    """
    Classify ensemble spread into a confidence tier.

    Args:
        spread: Standard deviation of ensemble member probabilities (0–1)

    Returns:
        "HIGH", "MODERATE", or "LOW"
    """
    if spread < 0.05:
        return "HIGH"
    if spread < 0.15:
        return "MODERATE"
    return "LOW"


def get_min_edge_for_confidence(spread: float, is_live: bool = False) -> float:
    """
    Return the minimum edge required for a trade given ensemble spread.

    Args:
        spread: Standard deviation of ensemble member probabilities (0–1)
        is_live: True for live trading, False for paper

    Returns:
        Minimum edge as a fraction (e.g. 0.05 = 5%)
    """
    tier = classify_confidence_tier(spread)
    mode = "live" if is_live else "paper"
    return _EDGE_TIERS[tier][mode]
```

- [x] **Step 4: Run tests to verify they pass**

```
python -m pytest tests/test_confidence_tiers.py -v
```

Expected: 7 tests PASSED

- [x] **Step 5: Wire into `_validate_trade_opportunity` in `main.py`**

Find the edge threshold check in `_validate_trade_opportunity`. It currently reads something like:
```python
min_edge = PAPER_MIN_EDGE if not live else MIN_EDGE
if edge < min_edge:
    return f"edge {edge:.1%} < {min_edge:.1%}"
```

Replace with:
```python
# Confidence-tiered edge threshold — spread from analysis result
ensemble_spread = opp.get("ensemble_spread", None)
if ensemble_spread is not None:
    try:
        from utils import get_min_edge_for_confidence
        min_edge = get_min_edge_for_confidence(float(ensemble_spread), is_live=bool(live))
    except Exception:
        min_edge = PAPER_MIN_EDGE if not live else MIN_EDGE
else:
    min_edge = PAPER_MIN_EDGE if not live else MIN_EDGE

if edge < min_edge:
    return f"edge {edge:.1%} < {min_edge:.1%} (spread={ensemble_spread})"
```

Note: `opp.get("ensemble_spread")` will be None for older analysis results (backward compatible — falls back to existing flat threshold). When Phase C adds Gaussian/multi-model ensemble, it should populate `"ensemble_spread"` in the analysis result dict.

- [x] **Step 6: Run full test suite**

```
python -m pytest tests/test_confidence_tiers.py tests/test_trade_validation.py tests/test_edge_threshold.py -v
```

Expected: all pass

- [x] **Step 7: Commit**

```bash
git add utils.py tests/test_confidence_tiers.py main.py
git commit -m "feat(risk): add confidence-tiered edge thresholds; HIGH(5%)/MODERATE(7%)/LOW(10%) based on ensemble spread"
```

---

## Final Integration Test

- [x] **Step 1: Run full test suite**

```
python -m pytest -x -q
```

Expected: all pass, no regressions

- [x] **Step 2: Commit & finish**

```bash
git commit -m "feat(phase-b): risk engine complete — drawdown tiers + flash crash CB + confidence-tiered thresholds"
```
