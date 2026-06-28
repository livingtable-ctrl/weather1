# Category LV: Long-term Visionary — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 10 research-grade improvements that require significant ML engineering or market research before implementation. These are designed for the phase after graduation (150+ settled trades, EMOS live, Brier ≤ 0.23).

**Architecture:** Each item in this category is a standalone R&D project. LV1 (settlement-time temperature model) and LV6 (regime-based strategy switching) are the two most likely to produce meaningful P&L improvement within 6 months. LV4 (market microstructure) and LV9 (A/B anchor test) are medium-term. The others are 1–3 year research bets.

**Prerequisites for this entire category:**
- EMOS deployed and running for 30+ days (A1 complete)
- Graduation gate met (Brier ≤ 0.23 on last 50 trades)
- At least 150 settled multi-day trades in the DB

**Implementation Order:** LV6 → LV9 → LV1 → LV4 → LV2 → LV5 → LV3 → LV7 → LV8 → LV10

---

## LV6: Regime-Based Strategy Switching

**Problem:** The bot uses the same blend weights and Kelly fractions regardless of atmospheric regime. During heat domes, ensemble models are more reliable than climatology (extreme events are well-modeled by ICON/ECMWF). During blocking-high patterns, the spread narrows and model confidence should increase. During volatile regimes, all models are less reliable. `regime.py` already detects these states but only modifies `ci_adjusted_kelly` — not the blend weights or market anchor.

**Files:**
- Read: `regime.py` (full file — already read in audit session; confirms 5 regimes with `detect_regime()`)
- Modify: `weather_markets.py` — use regime to select blend weights BEFORE condition/seasonal lookup
- Modify: `weather_markets.py` — use regime to adjust market anchor weight
- Test: `tests/test_forecasting.py`

### Research phase (do first)

- [ ] **Step 1: Backtest regime performance**

Query settled trades with regime labels to see if ensemble wins more in heat_dome/cold_snap vs volatile:

```python
# In a Jupyter notebook or py script:
from tracker import _conn, init_db
init_db()
with _conn() as con:
    rows = con.execute("""
        SELECT p.regime, p.won, p.net_edge, p.our_prob, o.settled_temp_f
        FROM   multiday_predictions p
        JOIN   outcomes o ON o.ticker = p.ticker
        WHERE  p.regime IS NOT NULL AND p.won IS NOT NULL
    """).fetchall()

from collections import defaultdict
by_regime = defaultdict(list)
for regime, won, net_edge, our_prob, settled_temp in rows:
    by_regime[regime].append(int(bool(won)))

for regime, wins in by_regime.items():
    print(f"{regime}: {sum(wins)}/{len(wins)} = {sum(wins)/len(wins):.2%} win rate")
```

If heat_dome/cold_snap win rate is > 70% and volatile is < 45%, regime weighting is justified. If all regimes show similar win rates, skip LV6.

- [ ] **Step 2: Define regime-specific blend weights**

Based on backtest results, define a mapping. Starting point (adjust based on your data):

```python
# weather_markets.py — add after _CONDITION_WEIGHTS definition
_REGIME_BLEND_OVERRIDES: dict[str, dict] = {
    "heat_dome": {
        # ECMWF/ICON ensemble members are excellent at extreme heat — upweight ensemble
        "above": {"ens": 0.75, "nws": 0.20, "clim": 0.05},
        "below": {"ens": 0.30, "nws": 0.30, "clim": 0.40},
        "between": {"ens": 0.60, "nws": 0.40, "clim": 0.00},
        "market_anchor_multiplier": 0.80,  # trust model more, anchor market less
    },
    "cold_snap": {
        "above": {"ens": 0.50, "nws": 0.30, "clim": 0.20},
        "below": {"ens": 0.75, "nws": 0.20, "clim": 0.05},
        "between": {"ens": 0.60, "nws": 0.40, "clim": 0.00},
        "market_anchor_multiplier": 0.80,
    },
    "volatile": {
        # All models less reliable; use NWS (human forecasters account for uncertainty)
        "above": {"ens": 0.35, "nws": 0.55, "clim": 0.10},
        "below": {"ens": 0.10, "nws": 0.60, "clim": 0.30},
        "between": {"ens": 0.20, "nws": 0.70, "clim": 0.10},
        "market_anchor_multiplier": 1.30,  # trust market more in volatile regime
    },
    "blocking_high": {
        # Low variance; ensemble should be very reliable
        "above": {"ens": 0.65, "nws": 0.30, "clim": 0.05},
        "below": {"ens": 0.20, "nws": 0.40, "clim": 0.40},
        "between": {"ens": 0.70, "nws": 0.30, "clim": 0.00},
        "market_anchor_multiplier": 0.70,
    },
    # "normal" uses existing _CONDITION_WEIGHTS — no override
}
```

- [ ] **Step 3: Write failing test**

```python
# tests/test_forecasting.py — add
def test_heat_dome_regime_upweights_ensemble(monkeypatch):
    import weather_markets as wm

    # Simulate heat_dome regime detection
    monkeypatch.setattr(wm, "_detect_current_regime", lambda *a, **k: "heat_dome")

    weights = wm._get_blend_weights(condition_type="above", regime="heat_dome")
    # In heat_dome, ensemble weight should be > 0.70
    assert weights["ens"] >= 0.70, f"heat_dome should upweight ensemble, got {weights['ens']}"

def test_volatile_regime_upweights_nws(monkeypatch):
    import weather_markets as wm
    weights = wm._get_blend_weights(condition_type="above", regime="volatile")
    assert weights["nws"] >= 0.50, f"volatile should upweight NWS, got {weights['nws']}"
```

- [ ] **Step 4: Add `_get_blend_weights(condition_type, regime)` to `weather_markets.py`**

```python
def _get_blend_weights(condition_type: str, regime: str | None = None) -> dict:
    """Return {ens, nws, clim} blend weights for a condition type and atmospheric regime.

    Falls back to _CONDITION_WEIGHTS[condition_type] when regime has no override
    or regime detection is unavailable.
    """
    if regime and regime in _REGIME_BLEND_OVERRIDES:
        override = _REGIME_BLEND_OVERRIDES[regime]
        if condition_type in override:
            return dict(override[condition_type])

    # Default to condition-type weights
    cw = _CONDITION_WEIGHTS.get(condition_type, {})
    return {
        "ens":  cw.get("ens",  0.33),
        "nws":  cw.get("nws",  0.33),
        "clim": cw.get("clim", 0.34),
    }
```

- [ ] **Step 5: Wire into `analyze_trade`**

In `analyze_trade`, where `w_ens`, `w_nws`, `w_clim` are currently read from `_CONDITION_WEIGHTS`, replace:

```python
# old:
w_ens  = _CONDITION_WEIGHTS[condition_type].get("ens", 0.33)
w_nws  = _CONDITION_WEIGHTS[condition_type].get("nws", 0.33)
w_clim = _CONDITION_WEIGHTS[condition_type].get("clim", 0.34)

# new:
from regime import detect_regime
_forecast_temps = enriched.get("forecast_temps_sample", temps)
_regime = detect_regime(_forecast_temps) if _forecast_temps else None
_weights = _get_blend_weights(condition_type, _regime)
w_ens, w_nws, w_clim = _weights["ens"], _weights["nws"], _weights["clim"]
```

Also apply `market_anchor_multiplier`:

```python
_anchor_mult = 1.0
if _regime and _regime in _REGIME_BLEND_OVERRIDES:
    _anchor_mult = _REGIME_BLEND_OVERRIDES[_regime].get("market_anchor_multiplier", 1.0)
_effective_anchor = _MARKET_ANCHOR_ABOVE * _anchor_mult  # or _BELOW depending on condition
```

- [ ] **Step 6: Run the tests**

```
pytest tests/test_forecasting.py -k "regime" -v
```
Expected: PASS

- [ ] **Step 7: Commit**

```
git add weather_markets.py regime.py tests/test_forecasting.py
git commit -m "feat(strategy): regime-based blend weight selection — heat_dome upweights ensemble, volatile upweights NWS"
```

---

## LV9: A/B Test Market Anchor Weight

**Problem:** The market anchor weight (currently 10% for above/below, 25% for between) is set empirically. We don't know if 10% or 5% or 20% produces better Brier scores over time. This requires a controlled A/B test.

**Files:**
- Modify: `ab_test.py` — add market anchor A/B test alongside existing PAPER_MIN_EDGE test
- Modify: `weather_markets.py` — look up active A/B variant for market anchor
- Modify: `tracker.py` — store `ab_variant` in the predictions table

- [ ] **Step 1: Confirm AB test framework API**

Read `ab_test.py` to understand the existing `ABTest` class. Confirm:
- How variants are declared
- How you get the active variant for a ticker
- How the variant is recorded for attribution

```python
from ab_test import ABTest
help(ABTest)
```

- [ ] **Step 2: Add `get_variant(ticker)` and `get_variant_config(variant)` to `ABTest` in `ab_test.py`**

The existing `ABTest` class (as of 2026-06-27) has `pick_variant()` (round-robin, no ticker arg) and `record_outcome()`. It does NOT have hash-based deterministic assignment by ticker. Add these two methods:

```python
# In class ABTest (ab_test.py), add after record_outcome():

def get_variant(self, ticker: str) -> str:
    """Return the variant deterministically assigned to this ticker (hash-based).

    Same ticker always returns the same variant name regardless of call order.
    Exhausted or disabled variants are excluded; falls back to the first active
    variant when all are exhausted.
    """
    import hashlib
    active = [
        v for v in self.variants
        if not self._state[v]["disabled"]
        and self._state[v]["trades"] < self.max_trades_per_variant
    ]
    if not active:
        return "control" if "control" in self.variants else next(iter(self.variants))

    # Hash ticker to an index into the active variant list
    h = int(hashlib.md5((self.name + ticker).encode()).hexdigest(), 16)
    return active[h % len(active)]

def get_variant_config(self, variant: str):
    """Return the variant value (dict, float, etc.) for the named variant.

    Raises KeyError if variant is not in self.variants.
    """
    return self.variants[variant]
```

- [ ] **Step 3: Declare the anchor A/B test**

```python
# In ab_test.py (module level, after the ABTest class definition):
MARKET_ANCHOR_ABTEST = ABTest(
    name="market_anchor_above",
    variants={
        "low":    {"above": 0.05, "below": 0.05},
        "medium": {"above": 0.10, "below": 0.10},  # current default
        "high":   {"above": 0.20, "below": 0.15},
    },
    max_trades_per_variant=50,
)
```

- [ ] **Step 4: Write failing test**

```python
# tests/test_ab_test.py — add
def test_anchor_abtest_assigns_consistently_for_same_ticker():
    from ab_test import ABTest
    ab = ABTest(
        name="test_anchor",
        variants={"low": 0.05, "medium": 0.10, "high": 0.20},
        max_trades_per_variant=100,
    )
    # Same ticker must return the same variant on every call (hash-based, deterministic)
    v1 = ab.get_variant("KXHIGHNY-26JUL04-T72")
    v2 = ab.get_variant("KXHIGHNY-26JUL04-T72")
    assert v1 == v2, f"get_variant must be deterministic: {v1} != {v2}"
    assert v1 in {"low", "medium", "high"}, f"Variant must be declared: {v1}"

def test_anchor_abtest_get_variant_config_returns_dict():
    from ab_test import ABTest
    ab = ABTest(
        name="test_anchor2",
        variants={"medium": {"above": 0.10, "below": 0.10}},
        max_trades_per_variant=100,
    )
    v = ab.get_variant("KXHIGHNY-26JUL04-T72")
    config = ab.get_variant_config(v)
    assert isinstance(config, dict), f"get_variant_config must return the variant dict"
    assert "above" in config
```

- [ ] **Step 5: Wire into `analyze_trade`**

In `analyze_trade`, where the market anchor weight is applied, add:

```python
try:
    from ab_test import MARKET_ANCHOR_ABTEST
    _anchor_variant = MARKET_ANCHOR_ABTEST.get_variant(ticker)
    _anchor_config = MARKET_ANCHOR_ABTEST.get_variant_config(_anchor_variant)
    _effective_anchor = _anchor_config.get(condition["type"], _MARKET_ANCHOR_ABOVE)
except Exception:
    _effective_anchor = _MARKET_ANCHOR_ABOVE  # fallback to default
```

Store the variant in the returned dict:

```python
"ab_anchor_variant": _anchor_variant,
```

- [ ] **Step 6: Store variant in predictions table**

Add `ab_anchor_variant TEXT` column to the next schema migration in `tracker.py`. Store when recording a prediction:

```python
# In record_prediction() or equivalent:
ab_anchor_variant=signal.get("ab_anchor_variant"),
```

- [ ] **Step 7: Add variant analysis query to `tracker.py`**

```python
def get_ab_test_results(test_name: str = "market_anchor_above") -> dict:
    """Return per-variant Brier score for A/B comparison."""
    init_db()
    with _conn() as con:
        rows = con.execute(
            """
            SELECT p.ab_anchor_variant,
                   AVG((p.our_prob - p.settled_yes) * (p.our_prob - p.settled_yes)) as brier,
                   COUNT(*) as n
            FROM   multiday_predictions p
            WHERE  p.ab_anchor_variant IS NOT NULL
              AND  p.settled_yes IS NOT NULL
            GROUP  BY p.ab_anchor_variant
            HAVING COUNT(*) >= 20
            """
        ).fetchall()
    return {r[0]: {"brier": round(r[1], 4), "n": r[2]} for r in rows}
```

- [ ] **Step 8: Add to `/api/ab-results` in `web_app.py`**

```python
@_app.route("/api/ab-results")
@_require_auth
def api_ab_results():
    from tracker import get_ab_test_results
    return get_ab_test_results()
```

- [ ] **Step 9: Run the tests and commit**

```
pytest tests/test_ab_test.py -v
```

```
git add ab_test.py weather_markets.py tracker.py web_app.py
git commit -m "feat(strategy): A/B test market anchor weights (5%/10%/20% for above/below)"
```

---

## LV1: Settlement-Time Temperature Model

**Problem:** Kalshi markets for HIGH temperature settle on the NWS Climate Data report. This report uses ASOS stations and has a specific definition of "daily high" (the highest reading in the 24h period from midnight to midnight local time). The NWS CLI report can be scraped. A model that predicts the gap between the NWS official high and the ensemble max over the 24h window would reduce settlement uncertainty.

**Research scope:**
- Scrape or API-call NWS CLI for 90 days of official highs per city
- Compare against ensemble 24h max from Previous Runs API for the same dates
- Fit a simple linear regression: `cli_high = a + b * ens_24h_max + c * dew_depression + d * station_bias`

**Files:**
- New: `nws_cli.py` — scraper for NWS CLI reports (already partly implemented per standing rules)
- New: `settlement_model.py` — linear regression on (ens_24h_max, dew_depression, hour_of_day) → cli_high
- Modify: `weather_markets.py` — apply settlement model correction before threshold comparison

**When to implement:** After 60+ settled above-condition trades; compare `settled_temp_f` in DB against what the ensemble predicted to quantify the gap.

*Requires custom data pipeline; estimate 2-3 weeks of engineering.*

---

## LV2: Marginal Kelly (Portfolio Covariance)

*See Category B plan (B4) for the full specification. Deferred until B2 (dynamic correlations) has 90+ days of data.*

---

## LV3: HRRR Intraday Update

**Problem:** For same-day markets, HRRR updates every hour. The current system checks HRRR once at scan time. A process that updates same-day probability estimates hourly as new HRRR runs become available would significantly improve same-day accuracy.

**Implementation path:**
1. Add an hourly cron task (separate from the main scan) that only processes same-day open positions
2. For each same-day open position, re-fetch HRRR hourly temps and update `blended_prob` in the predictions table
3. If the updated `blended_prob` crosses the early-exit threshold, trigger `check_early_exits`

*Blocked by the same-day data accumulation requirement (currently ~99 settled; need 150 before optimizing the same-day path).*

---

## LV4: Market Microstructure Scoring

**Problem:** Kalshi market bid-ask spreads and order book depth vary significantly. A market with a $0.02 spread has much lower transaction costs than one with a $0.10 spread. Incorporating spread and volume data into the Kelly fraction would improve actual realized P&L.

**Data available via Kalshi API:**
- `yes_bid`, `yes_ask` (currently used)
- `volume` (not currently used)
- `open_interest` (not currently used)

**Implementation path:**
1. Add `volume` and `open_interest` to the market data fetch in `weather_markets.py`
2. Compute `effective_spread = yes_ask - yes_bid`
3. Compute `liquidity_score = min(1.0, log10(volume + 1) / 4.0)` (0-1 scale)
4. Apply `microstructure_kelly_multiplier = 0.50 + 0.50 * liquidity_score` — thin markets get half Kelly
5. Include `effective_spread` in the edge calculation: `net_edge = model_edge - 0.5 * effective_spread`

**Files:**
- Modify: `weather_markets.py` — fetch volume/open_interest, compute microstructure multiplier
- Modify: `tracker.py` — add `volume`, `spread` columns to predictions table
- Test: `tests/test_forecasting.py`

*Straightforward to implement — blocked only by waiting for EMOS to stabilize (60+ days post-deployment).*

---

## LV5: Ensemble Member Clustering

**Problem:** When NAM (4 members), GFS (30 members), ICON (39 members), and ECMWF (50 members) all agree, the ensemble is reliable. But when two models form distinct clusters, that's a different situation than random spread. The current code treats all 119 members as a flat ensemble.

**Approach:**
1. Before computing `ens_stats`, apply k-means(k=2) to the temperature values (using `_detect_bimodal_ensemble` from A3)
2. For each cluster, compute cluster mean and within-cluster std
3. Report the cluster separation and membership counts in the returned `ens_stats` dict
4. Use cluster separation as a Kelly multiplier (already done by A3; this is about labeling WHICH models are in which cluster)

**Files:**
- Modify: `weather_markets.py` — `_compute_ens_stats()` or equivalent to include cluster labels

*R&D project — low urgency post-EMOS deployment since A3 already handles the bimodal case.*

---

## LV7: Cross-Market Signals

**Problem:** If the market for "Chicago HIGH > 95°F" is trading at 30%, and "Houston HIGH > 100°F" is trading at 40%, and the correlation between Chicago and Houston daily highs is 0.65, then these prices are likely inconsistent. Exploiting cross-market inconsistencies is a form of statistical arbitrage.

**Prerequisites:**
- B2 (dynamic correlations) must be live with 60+ days of data
- Portfolio EV (B3) must be live to assess combined position risk

**Implementation approach:**
- For each pair of cities/conditions detected as correlated (r > 0.5), compute the joint probability under a bivariate normal
- If the product of market prices deviates from the joint probability by more than 5%, flag as a cross-market opportunity
- Size the pair trade to be dollar-neutral (long underpriced, short overpriced)

*1-2 year research project. Do not attempt until 300+ settled multi-city pairs.*

---

## LV8: Natural Language Daily Brief

**Problem:** The operator has to look at 4 dashboard tabs to understand what happened today. A natural language summary ("Yesterday: 3 wins, 2 losses. Chicago above was a $12 winner — ICON had it right at 0.78. Houston below missed — all models said cool but ASOS hit 94°F. Today: 2 active positions with moderate edge.") would dramatically reduce monitoring time.

**Implementation approach:**
- Query settled trades from yesterday + open positions for today
- Format a structured context dict with all relevant numbers
- Pass to Claude API (`claude-haiku-4-5-20251001` for speed/cost) with a system prompt: "Generate a concise, plain-English morning brief for a prediction market trader."
- Send via the ntfy.sh push notification channel

**Files:**
- New: `daily_brief.py` — builds context + calls Claude API + sends push notification
- Modify: `cron.py` — call `daily_brief.generate_and_send()` at 09:00 UTC daily

**Cost estimate:** ~500 tokens per brief × 30 days = ~15,000 tokens/month = <$0.01/month with Haiku.

*Low engineering effort post-graduation. Main prerequisite is NTFY_TOPIC configured (E4 dead man's switch).*

---

## LV10: Kalshi Settlement Outcome Database

**Problem:** The system knows about markets it trades but not the universe of Kalshi weather markets. Building a comprehensive settlement history for all cities and all markets (traded or not) would:
1. Enable training EMOS on more data (not just our trades)
2. Enable backtesting strategies we never traded
3. Enable detecting when the market is systematically mispriced vs historical patterns

**Data source:** Kalshi `/markets/{ticker}/history` endpoint returns historical market data.

**Implementation:**
- New: `kalshi_archive.py` — fetches and stores all historical Kalshi weather market settlements
- New: `archive_predictions.db` — separate SQLite database for the full historical archive
- New: `py main.py archive-backfill` — fetches all available historical data for KXHIGH markets

*6-12 month research project. Primary value is enabling better EMOS training data quality.*
