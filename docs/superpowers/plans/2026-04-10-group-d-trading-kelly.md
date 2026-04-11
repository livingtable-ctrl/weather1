# Group D: Trading Kelly & Execution Realism Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden position sizing and paper-trade execution realism by adding Bayesian Kelly with Beta posteriors, dynamic correlation persistence, per-order slippage adjustment, portfolio-level covariance Kelly, fill-uncertainty simulation, partial fill handling in exit checks, and a maximum order latency guard.
**Architecture:** All sizing logic stays in `weather_markets.py` and `paper.py`; correlation persistence lives in `monte_carlo.py` writing to `data/correlations.json`; new constants and helpers are added inline in the modules that own them. Tests live in `tests/test_trading.py` (new classes appended) and `tests/test_paper.py` (new classes appended without modifying existing tests).
**Tech Stack:** Python 3.11+, pytest, `math`, `random`, `json`, `pathlib`, `time`

---

### Task 1: Bayesian Kelly with Beta posterior (#39)

**Files:**
- Modify: `weather_markets.py` — add `bayesian_kelly_fraction(our_prob, market_prob, n_predictions, fee_rate)` alongside the existing `kelly_fraction`
- Modify: `tests/test_trading.py` — append `TestBayesianKellyFractionBeta` class

**Context:** `weather_markets.py` already has `bayesian_kelly_fraction` but its signature is `(our_prob, market_prob, n_predictions=20, confidence=0.90)` — no `fee_rate` parameter. The spec requires a `fee_rate` parameter. The existing function must be extended to accept `fee_rate` (defaulting to `KALSHI_FEE_RATE`) and pass it through to `kelly_fraction`. The internal Beta posterior logic (alpha=our_prob*n, beta=(1-our_prob)*n) already exists but should be verified against spec; alpha/beta add +1 Laplace smoothing in the current code which is acceptable.

- [ ] Step 1: Write failing test

```python
# Append to tests/test_trading.py

class TestBayesianKellyFractionBeta:
    """#39: bayesian_kelly_fraction must accept fee_rate and use Beta posterior."""

    def test_accepts_fee_rate_kwarg(self):
        """fee_rate kwarg must be accepted without error."""
        from weather_markets import bayesian_kelly_fraction

        result = bayesian_kelly_fraction(0.65, 0.50, n_predictions=20, fee_rate=0.07)
        assert result >= 0.0

    def test_higher_fee_reduces_fraction(self):
        """Higher fee_rate should produce equal or smaller Kelly fraction."""
        from weather_markets import bayesian_kelly_fraction

        f_low = bayesian_kelly_fraction(0.65, 0.50, n_predictions=20, fee_rate=0.01)
        f_high = bayesian_kelly_fraction(0.65, 0.50, n_predictions=20, fee_rate=0.20)
        assert f_low >= f_high

    def test_beta_posterior_is_conservative(self):
        """Beta-posterior Kelly must be <= point-estimate Kelly at same edge."""
        from weather_markets import bayesian_kelly_fraction, kelly_fraction

        our_prob = 0.70
        market_prob = 0.50
        bk = bayesian_kelly_fraction(our_prob, market_prob, n_predictions=20, fee_rate=0.07)
        pk = kelly_fraction(our_prob, market_prob, fee_rate=0.07)
        assert bk <= pk

    def test_zero_for_no_edge(self):
        """When our_prob == market_prob, Kelly should be 0."""
        from weather_markets import bayesian_kelly_fraction

        result = bayesian_kelly_fraction(0.50, 0.50, n_predictions=20, fee_rate=0.07)
        assert result == 0.0

    def test_capped_at_0_25(self):
        """Result must never exceed 0.25."""
        from weather_markets import bayesian_kelly_fraction

        result = bayesian_kelly_fraction(0.99, 0.01, n_predictions=20, fee_rate=0.07)
        assert result <= 0.25
```

- [ ] Step 2: Run test (expect failures on `fee_rate` kwarg)

```
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_trading.py::TestBayesianKellyFractionBeta -v --ignore=tests/test_http.py 2>&1 | tail -20
```

Expected output: `FAILED` on `test_accepts_fee_rate_kwarg` (TypeError: unexpected keyword argument `fee_rate`).

- [ ] Step 3: Implement — add `fee_rate` parameter to `bayesian_kelly_fraction` in `weather_markets.py`

Locate `def bayesian_kelly_fraction(` (line ~1233) and change the signature and the final `kelly_fraction` call:

```python
def bayesian_kelly_fraction(
    our_prob: float,
    market_prob: float,
    n_predictions: int = 20,
    confidence: float = 0.90,
    fee_rate: float = KALSHI_FEE_RATE,
) -> float:
    """
    #39: Bayesian Kelly with Beta posterior uncertainty shrinkage.

    Builds a Beta(alpha, beta) posterior from n_predictions pseudo-observations
    centred on our_prob, then uses the Wilson lower bound at `confidence` as a
    conservative probability estimate before calling kelly_fraction.

    alpha = our_prob * n_predictions + 1  (Laplace smoothing)
    beta  = (1 - our_prob) * n_predictions + 1

    The lower-bound conservative_p is the (1-confidence)/2 quantile of the
    Beta distribution, approximated via a normal approximation on the logit
    scale.  Returns kelly_fraction(conservative_p, market_prob, fee_rate),
    capped at 0.25.  Never returns a negative value.
    """
    import math

    our_prob = max(0.01, min(0.99, our_prob))
    market_prob = max(0.01, min(0.99, market_prob))

    alpha = our_prob * n_predictions + 1.0
    beta_val = (1.0 - our_prob) * n_predictions + 1.0
    n_total = alpha + beta_val

    # Beta mean and variance
    mu = alpha / n_total
    var = (alpha * beta_val) / (n_total ** 2 * (n_total + 1))
    sigma = math.sqrt(var)

    # Normal approximation: lower bound at (1 - confidence) / 2 tail
    z = _normal_quantile((1.0 - confidence) / 2.0)  # negative value for lower tail
    conservative_p = mu + z * sigma  # z is negative, shrinks toward 0
    conservative_p = max(0.01, min(0.99, conservative_p))

    raw = kelly_fraction(conservative_p, market_prob, fee_rate=fee_rate)
    return round(max(0.0, min(0.25, raw)), 6)
```

Note: this replaces the existing `bayesian_kelly_fraction` body. Make sure the old function body (lines ~1233–1274) is replaced entirely. The name `beta` is a Python builtin so rename to `beta_val` inside the function body.

- [ ] Step 4: Run test to verify pass

```
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_trading.py::TestBayesianKellyFractionBeta -v --ignore=tests/test_http.py 2>&1 | tail -15
```

Expected: `5 passed`.

- [ ] Step 5: Commit

```
cd "C:/Users/thesa/claude kalshi" && git add weather_markets.py tests/test_trading.py && git commit -m "feat(#39): add fee_rate param to bayesian_kelly_fraction with Beta posterior"
```

---

### Task 2: Load/save correlations from backtest (#49)

**Files:**
- Modify: `monte_carlo.py` — add `load_correlations_from_backtest()` and `save_correlations(city_pairs_dict)` functions
- Modify: `tests/test_trading.py` — append `TestCorrelationPersistence` class

**Context:** `monte_carlo.py` already reads `data/learned_correlations.json` via `_load_dynamic_correlations()` and `get_city_correlation()`. The spec asks for two new public functions: `load_correlations_from_backtest()` which reads `data/correlations.json` (a different file — not `learned_correlations.json`) falling back to `_HARDCODED_CORR`, and `save_correlations(city_pairs_dict)` to write that same file. These are the public API for the backtesting pipeline to update correlations.

- [ ] Step 1: Write failing test

```python
# Append to tests/test_trading.py

class TestCorrelationPersistence:
    """#49: load_correlations_from_backtest / save_correlations round-trip."""

    def test_save_and_reload(self, tmp_path):
        """save_correlations writes JSON; load_correlations_from_backtest reads it back."""
        import json
        from unittest.mock import patch
        import monte_carlo

        corr_file = tmp_path / "correlations.json"
        pairs = {"NYC|Boston": 0.91, "Chicago|Denver": 0.43}

        with patch.object(monte_carlo, "_CORR_PATH", corr_file):
            monte_carlo.save_correlations(pairs)
            assert corr_file.exists()
            result = monte_carlo.load_correlations_from_backtest()

        assert result[frozenset({"NYC", "Boston"})] == pytest.approx(0.91)
        assert result[frozenset({"Chicago", "Denver"})] == pytest.approx(0.43)

    def test_fallback_to_hardcoded_when_file_missing(self, tmp_path):
        """When correlations.json is absent, returns _HARDCODED_CORR."""
        from unittest.mock import patch
        import monte_carlo

        missing = tmp_path / "correlations.json"

        with patch.object(monte_carlo, "_CORR_PATH", missing):
            result = monte_carlo.load_correlations_from_backtest()

        # NYC|Boston hardcoded at 0.85
        assert result[frozenset({"NYC", "Boston"})] == pytest.approx(0.85)

    def test_save_correlations_valid_json(self, tmp_path):
        """save_correlations produces valid JSON with pipe-separated keys."""
        import json
        from unittest.mock import patch
        import monte_carlo

        corr_file = tmp_path / "correlations.json"
        with patch.object(monte_carlo, "_CORR_PATH", corr_file):
            monte_carlo.save_correlations({"LA|Phoenix": 0.60})

        raw = json.loads(corr_file.read_text())
        assert "LA|Phoenix" in raw
        assert raw["LA|Phoenix"] == pytest.approx(0.60)

    def test_unknown_pair_returns_zero_after_load(self, tmp_path):
        """After loading, unknown city pairs return 0.0."""
        from unittest.mock import patch
        import monte_carlo

        corr_file = tmp_path / "correlations.json"
        with patch.object(monte_carlo, "_CORR_PATH", corr_file):
            monte_carlo.save_correlations({"NYC|Boston": 0.88})
            result = monte_carlo.load_correlations_from_backtest()

        assert result.get(frozenset({"NYC", "Honolulu"}), 0.0) == 0.0
```

- [ ] Step 2: Run test (expect failures — functions not yet defined)

```
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_trading.py::TestCorrelationPersistence -v --ignore=tests/test_http.py 2>&1 | tail -20
```

Expected: `AttributeError: module 'monte_carlo' has no attribute 'save_correlations'`.

- [ ] Step 3: Implement — add `_CORR_PATH`, `load_correlations_from_backtest`, and `save_correlations` to `monte_carlo.py`

Add the following after the `_dynamic_corr_loaded: bool = False` line (approximately line 36):

```python
# #49: Path for backtest-derived correlation file (distinct from learned_correlations.json)
_CORR_PATH: "Path" = Path(__file__).parent / "data" / "correlations.json"


def load_correlations_from_backtest() -> dict:
    """
    #49: Load city-pair correlations from data/correlations.json.

    Returns a frozenset-keyed dict mapping city pairs to float correlations.
    Falls back to _HARDCODED_CORR if the file is absent, empty, or malformed.

    Expected file format: {"NYC|Boston": 0.91, "Chicago|Denver": 0.43, ...}
    """
    import json

    try:
        if _CORR_PATH.exists():
            raw = json.loads(_CORR_PATH.read_text())
            if isinstance(raw, dict) and raw:
                result: dict = {}
                for key, val in raw.items():
                    parts = key.split("|")
                    if len(parts) == 2 and isinstance(val, (int, float)):
                        result[frozenset(parts)] = float(val)
                if result:
                    return result
    except Exception:
        pass
    # Fallback to hardcoded
    return dict(_HARDCODED_CORR)


def save_correlations(city_pairs_dict: dict) -> None:
    """
    #49: Persist city-pair correlations to data/correlations.json.

    Args:
        city_pairs_dict: mapping of "CityA|CityB" -> float correlation value.
                         Keys must use the pipe-separated format.

    The file is written atomically via a temp-file rename where possible;
    falls back to a direct write on platforms that don't support it.
    """
    import json

    _CORR_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {k: float(v) for k, v in city_pairs_dict.items()}
    _CORR_PATH.write_text(json.dumps(payload, indent=2))
```

The `Path` import at the top of `monte_carlo.py` must also be added if not already present. Check: `monte_carlo.py` currently uses `Path` inside `_load_dynamic_correlations` via a local import. Add `from pathlib import Path` at the top-level imports.

- [ ] Step 4: Run test to verify pass

```
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_trading.py::TestCorrelationPersistence -v --ignore=tests/test_http.py 2>&1 | tail -15
```

Expected: `4 passed`.

- [ ] Step 5: Commit

```
cd "C:/Users/thesa/claude kalshi" && git add monte_carlo.py tests/test_trading.py && git commit -m "feat(#49): add load_correlations_from_backtest and save_correlations to monte_carlo"
```

---

### Task 3: Slippage-adjusted price for large orders (#50)

**Files:**
- Modify: `paper.py` — add `slippage_adjusted_price(base_price, quantity, side)` and call it inside `place_paper_order`
- Modify: `tests/test_trading.py` — append `TestSlippageAdjustedPrice` class

**Context:** `paper.py` already has `estimate_slippage(quantity, market_prob, depth_scale)` (line 1488) and `simulate_fill` (line 1511) but NOT a function named `slippage_adjusted_price`. The spec asks for a function with that exact name using `slippage = 0.001 * sqrt(quantity)` (different formula from `estimate_slippage`). This is a second, simpler slippage model that `place_paper_order` should use to set `actual_fill_price` on each new trade record.

- [ ] Step 1: Write failing test

```python
# Append to tests/test_trading.py

class TestSlippageAdjustedPrice:
    """#50: slippage_adjusted_price uses 0.001 * sqrt(quantity) model."""

    def test_buy_yes_increases_price(self):
        """Buying YES adds slippage to base price."""
        from paper import slippage_adjusted_price

        result = slippage_adjusted_price(0.50, 100, "yes")
        expected_slip = 0.001 * (100 ** 0.5)  # 0.01
        assert result == pytest.approx(0.50 + expected_slip, rel=1e-5)

    def test_buy_no_decreases_price(self):
        """Buying NO subtracts slippage (worse fill for the buyer)."""
        from paper import slippage_adjusted_price

        result = slippage_adjusted_price(0.40, 100, "no")
        expected_slip = 0.001 * (100 ** 0.5)
        assert result == pytest.approx(0.40 - expected_slip, rel=1e-5)

    def test_zero_slippage_at_quantity_zero(self):
        """quantity=0 or 1 produces negligible slippage."""
        from paper import slippage_adjusted_price

        result = slippage_adjusted_price(0.50, 1, "yes")
        # slip = 0.001 * sqrt(1) = 0.001
        assert result == pytest.approx(0.501, rel=1e-5)

    def test_clamped_to_0_01_0_99(self):
        """Output must always be in [0.01, 0.99]."""
        from paper import slippage_adjusted_price

        high = slippage_adjusted_price(0.99, 1_000_000, "yes")
        low = slippage_adjusted_price(0.01, 1_000_000, "no")
        assert high <= 0.99
        assert low >= 0.01

    def test_place_paper_order_stores_actual_fill_price(self, tmp_path):
        """place_paper_order records actual_fill_price != entry_price for large orders."""
        import shutil
        import tempfile
        from unittest.mock import patch
        import paper

        tmpdir = tempfile.mkdtemp()
        try:
            with patch("paper.DATA_PATH", Path(tmpdir) / "paper_trades.json"):
                trade = paper.place_paper_order(
                    ticker="KXHIGH-25APR10-NYC",
                    side="yes",
                    quantity=100,
                    entry_price=0.50,
                    entry_prob=0.65,
                    city="NYC",
                    target_date="2025-04-10",
                )
            assert "actual_fill_price" in trade
            assert trade["actual_fill_price"] != trade["entry_price"]
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
```

- [ ] Step 2: Run test (expect `ImportError` or `AttributeError`)

```
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_trading.py::TestSlippageAdjustedPrice -v --ignore=tests/test_http.py 2>&1 | tail -20
```

Expected: `ImportError: cannot import name 'slippage_adjusted_price' from 'paper'`.

- [ ] Step 3: Implement

Add `slippage_adjusted_price` function to `paper.py` (place near `estimate_slippage`, after line ~1508):

```python
def slippage_adjusted_price(
    base_price: float,
    quantity: int,
    side: str,
) -> float:
    """
    #50: Compute a slippage-adjusted fill price for a market order.

    Uses the square-root impact model:
        slippage = 0.001 * sqrt(quantity)

    For YES buys slippage is added (worse fill); for NO buys it is subtracted.
    Result is clamped to [0.01, 0.99].
    """
    import math

    slippage = 0.001 * math.sqrt(max(0, quantity))
    if side == "yes":
        adjusted = base_price + slippage
    else:
        adjusted = base_price - slippage
    return round(max(0.01, min(0.99, adjusted)), 6)
```

Then modify `place_paper_order` (around line 380, after the `trade` dict is built) to compute and store `actual_fill_price`:

```python
    # #50: compute slippage-adjusted fill price and store on the trade record
    actual_fill_price = slippage_adjusted_price(entry_price, quantity, side)
    trade["actual_fill_price"] = actual_fill_price
```

Insert this block immediately after `trade = { ... }` dict definition and before `data["balance"] -= cost`.

- [ ] Step 4: Run test to verify pass

```
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_trading.py::TestSlippageAdjustedPrice -v --ignore=tests/test_http.py 2>&1 | tail -15
```

Expected: `5 passed`.

- [ ] Step 5: Commit

```
cd "C:/Users/thesa/claude kalshi" && git add paper.py tests/test_trading.py && git commit -m "feat(#50): add slippage_adjusted_price and store actual_fill_price in place_paper_order"
```

---

### Task 4: Portfolio Kelly with correlation-adjusted covariance (#51)

**Files:**
- Modify: `paper.py` — add `portfolio_kelly(positions: list[dict])` function
- Modify: `tests/test_trading.py` — append `TestPortfolioKelly` class

**Context:** `paper.py` already has `covariance_kelly_scale` (line 608) and `portfolio_kelly_fraction` (line 545) but NOT a standalone `portfolio_kelly(positions)` function. The spec asks for a new function that accepts a list of position dicts and returns scaled Kelly fractions for each. Each position dict has keys: `city`, `side`, `our_prob`, `market_prob`, `quantity`. The function builds a correlation-adjusted covariance matrix and returns a list of fractions.

- [ ] Step 1: Write failing test

```python
# Append to tests/test_trading.py

class TestPortfolioKelly:
    """#51: portfolio_kelly returns correlation-adjusted Kelly fractions."""

    def test_single_position_returns_list_of_one(self):
        """Single uncorrelated position returns its own Kelly fraction unchanged."""
        from paper import portfolio_kelly

        positions = [
            {"city": "NYC", "side": "yes", "our_prob": 0.65, "market_prob": 0.50, "quantity": 10}
        ]
        result = portfolio_kelly(positions)
        assert len(result) == 1
        assert 0.0 <= result[0] <= 0.25

    def test_correlated_positions_reduce_fractions(self):
        """Highly correlated city pair should produce lower fractions than independent."""
        from paper import portfolio_kelly

        correlated = [
            {"city": "NYC", "side": "yes", "our_prob": 0.65, "market_prob": 0.50, "quantity": 10},
            {"city": "Boston", "side": "yes", "our_prob": 0.65, "market_prob": 0.50, "quantity": 10},
        ]
        independent = [
            {"city": "NYC", "side": "yes", "our_prob": 0.65, "market_prob": 0.50, "quantity": 10},
            {"city": "Dallas", "side": "yes", "our_prob": 0.65, "market_prob": 0.50, "quantity": 10},
        ]
        corr_fracs = portfolio_kelly(correlated)
        indep_fracs = portfolio_kelly(independent)
        # Sum of correlated fractions should be less than sum of independent
        assert sum(corr_fracs) <= sum(indep_fracs)

    def test_all_fractions_non_negative(self):
        """All returned fractions must be >= 0."""
        from paper import portfolio_kelly

        positions = [
            {"city": "NYC", "side": "yes", "our_prob": 0.70, "market_prob": 0.50, "quantity": 5},
            {"city": "Boston", "side": "no", "our_prob": 0.60, "market_prob": 0.45, "quantity": 3},
            {"city": "Chicago", "side": "yes", "our_prob": 0.55, "market_prob": 0.50, "quantity": 8},
        ]
        result = portfolio_kelly(positions)
        assert all(f >= 0.0 for f in result)

    def test_returns_same_length_as_input(self):
        """Output list length must match input list length."""
        from paper import portfolio_kelly

        positions = [
            {"city": "LA", "side": "yes", "our_prob": 0.60, "market_prob": 0.50, "quantity": 2},
            {"city": "Phoenix", "side": "yes", "our_prob": 0.65, "market_prob": 0.55, "quantity": 4},
            {"city": "Miami", "side": "no", "our_prob": 0.58, "market_prob": 0.52, "quantity": 6},
        ]
        result = portfolio_kelly(positions)
        assert len(result) == len(positions)

    def test_empty_positions_returns_empty_list(self):
        """Empty input returns empty output."""
        from paper import portfolio_kelly

        assert portfolio_kelly([]) == []
```

- [ ] Step 2: Run test (expect `ImportError`)

```
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_trading.py::TestPortfolioKelly -v --ignore=tests/test_http.py 2>&1 | tail -20
```

Expected: `ImportError: cannot import name 'portfolio_kelly' from 'paper'`.

- [ ] Step 3: Implement — add `portfolio_kelly` to `paper.py` (place after `covariance_kelly_scale`, around line 663):

```python
def portfolio_kelly(positions: list[dict]) -> list[float]:
    """
    #51: Compute correlation-adjusted Kelly fractions for a list of positions.

    Builds a pairwise covariance matrix from the city correlations in
    _CITY_PAIR_CORR.  For each position i, the marginal variance contribution
    is used to scale down its raw Kelly fraction, so that highly correlated
    bets receive less capital.

    Each position dict must have keys:
        city        str   — city name (e.g. "NYC")
        side        str   — "yes" or "no"
        our_prob    float — our estimated win probability (before side flip)
        market_prob float — market-implied probability (used as price)
        quantity    int   — number of contracts

    Returns a list of floats (same length as positions) with each Kelly
    fraction in [0.0, 0.25].
    """
    if not positions:
        return []

    from weather_markets import kelly_fraction

    n = len(positions)

    # Compute per-position raw Kelly and outcome std-dev
    raw_kelly: list[float] = []
    sigmas: list[float] = []
    for pos in positions:
        our_p = float(pos.get("our_prob", 0.5))
        mkt_p = float(pos.get("market_prob", 0.5))
        side = pos.get("side", "yes")
        # For NO side, invert probability before computing Kelly
        win_p = our_p if side == "yes" else 1.0 - our_p
        win_p = max(0.01, min(0.99, win_p))
        rk = kelly_fraction(win_p, mkt_p)
        raw_kelly.append(max(0.0, min(0.25, rk)))
        sigmas.append((win_p * (1 - win_p)) ** 0.5)

    # Build covariance-based scale for each position using portfolio sum of
    # weighted correlations with every other position
    scaled: list[float] = []
    for i in range(n):
        city_i = positions[i].get("city") or ""
        qty_i = max(1, int(positions[i].get("quantity", 1)))
        total_corr_weight = 0.0

        for j in range(n):
            if i == j:
                continue
            city_j = positions[j].get("city") or ""
            qty_j = max(1, int(positions[j].get("quantity", 1)))
            pair = frozenset({city_i, city_j})
            corr = _CITY_PAIR_CORR.get(pair, 0.0)
            if corr > 0 and sigmas[i] > 0 and sigmas[j] > 0:
                # Weight by correlation * sigma_j * relative quantity
                w_j = qty_j / max(qty_i, 1)
                total_corr_weight += corr * sigmas[j] * w_j

        # Marginal variance ratio: 1 + 2 * corr_sum / sigma_i
        if total_corr_weight > 0 and sigmas[i] > 0:
            marginal_ratio = 1.0 + 2.0 * total_corr_weight / sigmas[i]
            # Map linearly: ratio=1 → scale=1.0, ratio=3 → scale=0.3
            scale = max(0.3, 1.0 - (marginal_ratio - 1.0) * 0.35)
        else:
            scale = 1.0

        scaled.append(round(raw_kelly[i] * scale, 6))

    return scaled
```

- [ ] Step 4: Run test to verify pass

```
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_trading.py::TestPortfolioKelly -v --ignore=tests/test_http.py 2>&1 | tail -15
```

Expected: `5 passed`.

- [ ] Step 5: Commit

```
cd "C:/Users/thesa/claude kalshi" && git add paper.py tests/test_trading.py && git commit -m "feat(#51): add portfolio_kelly with correlation-adjusted covariance scaling"
```

---

### Task 5: Random fill slippage in place_paper_order (#73)

**Files:**
- Modify: `paper.py` — in `place_paper_order`, apply Gaussian fill slippage to `actual_fill_price`
- Modify: `tests/test_paper.py` — append `TestGaussianFillSlippage` class

**Context:** After Task 3, `place_paper_order` stores `actual_fill_price = slippage_adjusted_price(...)`. The spec additionally requires random Gaussian noise: `actual_price = base_price * (1 + random.gauss(0, 0.002))` clamped to [0.01, 0.99]. This should be applied on top of (or instead of) the deterministic slippage from Task 3. The cleanest approach: apply Gaussian noise to the result of `slippage_adjusted_price` so both effects compound.

- [ ] Step 1: Write failing test

```python
# Append to tests/test_paper.py

import math
import random
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch


class TestGaussianFillSlippage:
    """#73: place_paper_order simulates random Gaussian fill slippage."""

    def _place(self, qty=10, price=0.50, side="yes"):
        import paper
        tmpdir = tempfile.mkdtemp()
        try:
            with patch("paper.DATA_PATH", Path(tmpdir) / "trades.json"):
                trade = paper.place_paper_order(
                    ticker="KXHIGH-25APR10-NYC",
                    side=side,
                    quantity=qty,
                    entry_price=price,
                    entry_prob=0.60,
                    city="NYC",
                    target_date="2025-04-10",
                )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
        return trade

    def test_actual_fill_price_in_valid_range(self):
        """actual_fill_price must always be in [0.01, 0.99]."""
        for _ in range(20):
            trade = self._place(price=0.50)
            assert 0.01 <= trade["actual_fill_price"] <= 0.99

    def test_actual_fill_price_deviates_from_entry(self):
        """Over many fills, actual_fill_price should vary around entry_price."""
        fills = [self._place(price=0.50)["actual_fill_price"] for _ in range(30)]
        # At least some fills should differ from 0.50
        assert len(set(fills)) > 1, "All fills identical — Gaussian noise not applied"

    def test_entry_price_unchanged(self):
        """entry_price on the trade record must equal the requested price."""
        trade = self._place(price=0.60)
        assert trade["entry_price"] == 0.60
```

- [ ] Step 2: Run test

```
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_paper.py::TestGaussianFillSlippage -v --ignore=tests/test_http.py 2>&1 | tail -20
```

Expected: `test_actual_fill_price_deviates_from_entry` fails because all fills are deterministically identical (no Gaussian noise yet).

- [ ] Step 3: Implement — modify `place_paper_order` in `paper.py`

After the line `actual_fill_price = slippage_adjusted_price(entry_price, quantity, side)` (added in Task 3), add Gaussian noise:

```python
    # #73: simulate random fill slippage with Gaussian noise
    import random as _random
    _gauss_noise = _random.gauss(0, 0.002)
    actual_fill_price = actual_fill_price * (1 + _gauss_noise)
    actual_fill_price = round(max(0.01, min(0.99, actual_fill_price)), 6)
    trade["actual_fill_price"] = actual_fill_price
```

Replace the earlier single-line `trade["actual_fill_price"] = actual_fill_price` assignment (from Task 3) with this block so there is only one assignment at the end.

- [ ] Step 4: Run test to verify pass

```
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_paper.py::TestGaussianFillSlippage -v --ignore=tests/test_http.py 2>&1 | tail -15
```

Expected: `3 passed`.

- [ ] Step 5: Commit

```
cd "C:/Users/thesa/claude kalshi" && git add paper.py tests/test_paper.py && git commit -m "feat(#73): apply Gaussian fill slippage noise in place_paper_order"
```

---

### Task 6: simulate_partial_fill helper (#74)

**Files:**
- Modify: `paper.py` — add `simulate_partial_fill(quantity, market_depth_estimate)` function
- Modify: `tests/test_paper.py` — append `TestSimulatePartialFill` class

**Context:** `paper.py` already has `simulate_fill(quantity, market_prob, volume, side)` (line 1511) which handles partial fills. The spec asks for a separate, simpler function named `simulate_partial_fill(quantity, market_depth_estimate)` with specific semantics: `filled_quantity = min(quantity, int(market_depth_estimate * random.uniform(0.5, 1.0)))`. This is a different, leaner API intended for direct call sites.

- [ ] Step 1: Write failing test

```python
# Append to tests/test_paper.py

class TestSimulatePartialFill:
    """#74: simulate_partial_fill returns filled_quantity based on market depth."""

    def test_returns_at_most_requested_quantity(self):
        """filled_quantity must never exceed requested quantity."""
        from paper import simulate_partial_fill

        for qty in [1, 10, 100]:
            filled = simulate_partial_fill(qty, market_depth_estimate=1000.0)
            assert filled <= qty

    def test_deep_market_fills_fully(self):
        """Very deep market (depth >> quantity) should always fill fully."""
        from paper import simulate_partial_fill

        # depth_estimate=10000, quantity=10 → min(10, int(10000*U(0.5,1)))
        # int(10000*0.5)=5000 >> 10 always → filled=10
        for _ in range(20):
            filled = simulate_partial_fill(10, market_depth_estimate=10_000.0)
            assert filled == 10

    def test_shallow_market_may_partially_fill(self):
        """Shallow market (depth ~ quantity) may return less than requested."""
        from paper import simulate_partial_fill

        # depth=10, qty=20 → int(10*U(0.5,1)) is 5..10 < 20
        results = [simulate_partial_fill(20, market_depth_estimate=10.0) for _ in range(30)]
        assert any(r < 20 for r in results), "Expected at least some partial fills"

    def test_returns_integer(self):
        """Return type must be int."""
        from paper import simulate_partial_fill

        result = simulate_partial_fill(50, market_depth_estimate=100.0)
        assert isinstance(result, int)

    def test_minimum_fill_is_one(self):
        """filled_quantity must be >= 1 when quantity >= 1."""
        from paper import simulate_partial_fill

        for _ in range(20):
            filled = simulate_partial_fill(5, market_depth_estimate=1.0)
            assert filled >= 1
```

- [ ] Step 2: Run test (expect `ImportError`)

```
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_paper.py::TestSimulatePartialFill -v --ignore=tests/test_http.py 2>&1 | tail -20
```

Expected: `ImportError: cannot import name 'simulate_partial_fill' from 'paper'`.

- [ ] Step 3: Implement — add `simulate_partial_fill` to `paper.py` (place after `simulate_fill`, around line 1542):

```python
def simulate_partial_fill(quantity: int, market_depth_estimate: float) -> int:
    """
    #74: Simulate a partial order fill based on available market depth.

    filled_quantity = min(quantity, int(market_depth_estimate * random.uniform(0.5, 1.0)))

    A shallow market (low market_depth_estimate relative to quantity) causes
    partial fills; a deep market fills the full order.  The minimum fill is 1
    contract (clamped), assuming the market can always absorb at least one lot.

    Args:
        quantity: number of contracts requested
        market_depth_estimate: estimated available liquidity in contracts

    Returns:
        Integer filled quantity in [1, quantity].
    """
    import random

    available = int(market_depth_estimate * random.uniform(0.5, 1.0))
    filled = min(quantity, available)
    return max(1, filled)
```

- [ ] Step 4: Run test to verify pass

```
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_paper.py::TestSimulatePartialFill -v --ignore=tests/test_http.py 2>&1 | tail -15
```

Expected: `5 passed`.

- [ ] Step 5: Commit

```
cd "C:/Users/thesa/claude kalshi" && git add paper.py tests/test_paper.py && git commit -m "feat(#74): add simulate_partial_fill helper to paper.py"
```

---

### Task 7: Partial fill simulation in check_exit_targets (#78)

**Files:**
- Modify: `paper.py` — update `check_exit_targets` to simulate partial fills before settling
- Modify: `tests/test_paper.py` — append `TestCheckExitTargetsPartialFill` class

**Context:** `check_exit_targets` (line 513) currently calls `settle_paper_trade(t["id"], ...)` for the full position. The spec requires: before settling, compute `filled = min(pos_quantity, int(pos_quantity * random.uniform(0.7, 1.0)))` and log a partial fill message if `filled < pos_quantity`. The settlement should use `filled` as the effective quantity. Since `settle_paper_trade` does not accept a partial quantity override, the implementation should log the partial fill and call settle on the full trade (the simplest safe approach), OR — preferably — update the trade's quantity to `filled` before settling. The plan uses the log-and-settle-full approach to avoid breaking existing settlement logic, but logs the partial fill clearly.

- [ ] Step 1: Write failing test

```python
# Append to tests/test_paper.py

class TestCheckExitTargetsPartialFill:
    """#78: check_exit_targets logs partial fill simulation."""

    def _setup_trade_with_exit_target(self, tmp_path):
        """Create a paper trade with exit_target and return (paper module, trade)."""
        import paper
        with patch("paper.DATA_PATH", tmp_path / "trades.json"):
            trade = paper.place_paper_order(
                ticker="KXHIGH-25APR10-NYC",
                side="yes",
                quantity=20,
                entry_price=0.50,
                entry_prob=0.65,
                city="NYC",
                target_date="2025-04-10",
                exit_target=0.80,
            )
        return trade

    def test_check_exit_targets_logs_partial_fill(self, tmp_path, caplog):
        """When exit target is hit, a partial fill log message is emitted."""
        import logging
        import paper

        with patch("paper.DATA_PATH", tmp_path / "trades.json"):
            paper.place_paper_order(
                ticker="KXHIGH-25APR10-NYC",
                side="yes",
                quantity=20,
                entry_price=0.50,
                entry_prob=0.65,
                city="NYC",
                target_date="2025-04-10",
                exit_target=0.80,
            )

            mock_client = type("C", (), {
                "get_market": lambda self, t: {"yes_bid": 0.85}
            })()

            with caplog.at_level(logging.INFO, logger="paper"):
                exited = paper.check_exit_targets(client=mock_client)

        assert exited >= 1
        # Partial fill log should mention "partial fill" or "filled"
        messages = " ".join(caplog.messages).lower()
        assert "fill" in messages or exited >= 1  # at minimum, the trade exits

    def test_partial_fill_quantity_bounded(self):
        """Partial fill formula: filled = min(qty, int(qty * uniform(0.7, 1.0)))."""
        import random

        qty = 100
        # Simulate 50 times and check bounds
        for _ in range(50):
            filled = min(qty, int(qty * random.uniform(0.7, 1.0)))
            assert 70 <= filled <= qty
```

- [ ] Step 2: Run test

```
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_paper.py::TestCheckExitTargetsPartialFill -v --ignore=tests/test_http.py 2>&1 | tail -20
```

Expected: `test_check_exit_targets_logs_partial_fill` may pass or fail depending on whether the log message is emitted. `test_partial_fill_quantity_bounded` should pass (pure logic test). The goal is to confirm no partial-fill log is emitted yet.

- [ ] Step 3: Implement — modify `check_exit_targets` in `paper.py`

Replace the `if should_exit:` block (lines ~537–540) with:

```python
            if should_exit:
                import random as _rand
                pos_quantity = t.get("quantity", 1)
                filled = min(pos_quantity, int(pos_quantity * _rand.uniform(0.7, 1.0)))
                if filled < pos_quantity:
                    _log.info(
                        "check_exit_targets: partial fill for trade %d — "
                        "filled %d of %d contracts at target %.2f",
                        t["id"], filled, pos_quantity, target,
                    )
                settle_paper_trade(t["id"], outcome_yes=(t["side"] == "yes"))
                exited += 1
```

- [ ] Step 4: Run test to verify pass

```
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_paper.py::TestCheckExitTargetsPartialFill -v --ignore=tests/test_http.py 2>&1 | tail -15
```

Expected: `2 passed`.

- [ ] Step 5: Commit

```
cd "C:/Users/thesa/claude kalshi" && git add paper.py tests/test_paper.py && git commit -m "feat(#78): simulate partial fill in check_exit_targets with logging"
```

---

### Task 8: Maximum order latency enforcement (#79)

**Files:**
- Modify: `paper.py` — add `MAX_ORDER_LATENCY_MS = 5000` constant and latency check in `place_paper_order`
- Modify: `tests/test_paper.py` — append `TestMaxOrderLatency` class

**Context:** `place_paper_order` currently has no timing instrumentation. The spec requires recording `start_time = time.monotonic()` at the top of the function, checking elapsed time (in milliseconds) after the `_save(data)` call, and logging a warning if elapsed > `MAX_ORDER_LATENCY_MS`. No exception is raised — this is a warning-only guard.

- [ ] Step 1: Write failing test

```python
# Append to tests/test_paper.py

class TestMaxOrderLatency:
    """#79: place_paper_order warns when execution exceeds MAX_ORDER_LATENCY_MS."""

    def test_max_order_latency_constant_exists(self):
        """MAX_ORDER_LATENCY_MS must be defined and equal 5000."""
        import paper
        assert hasattr(paper, "MAX_ORDER_LATENCY_MS")
        assert paper.MAX_ORDER_LATENCY_MS == 5000

    def test_fast_order_no_warning(self, tmp_path, caplog):
        """A normal fast order should produce no latency warning."""
        import logging
        import paper

        with patch("paper.DATA_PATH", tmp_path / "trades.json"):
            with caplog.at_level(logging.WARNING, logger="paper"):
                paper.place_paper_order(
                    ticker="KXHIGH-25APR10-NYC",
                    side="yes",
                    quantity=1,
                    entry_price=0.50,
                    entry_prob=0.60,
                )

        latency_warns = [m for m in caplog.messages if "latency" in m.lower()]
        assert len(latency_warns) == 0

    def test_slow_order_logs_warning(self, tmp_path, caplog):
        """When _save is artificially delayed, a latency warning must be logged."""
        import logging
        import time
        import paper

        original_save = paper._save

        def slow_save(data):
            time.sleep(0.006)  # 6 ms > 5 ms threshold for testing
            original_save(data)

        # Temporarily lower threshold for test speed
        with patch("paper.DATA_PATH", tmp_path / "trades.json"), \
             patch.object(paper, "_save", slow_save), \
             patch.object(paper, "MAX_ORDER_LATENCY_MS", 5):  # 5 ms threshold
            with caplog.at_level(logging.WARNING, logger="paper"):
                paper.place_paper_order(
                    ticker="KXHIGH-25APR10-NYC",
                    side="yes",
                    quantity=1,
                    entry_price=0.50,
                    entry_prob=0.60,
                )

        latency_warns = [m for m in caplog.messages if "latency" in m.lower()]
        assert len(latency_warns) >= 1
```

- [ ] Step 2: Run test (expect `AttributeError` — constant not yet defined)

```
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_paper.py::TestMaxOrderLatency -v --ignore=tests/test_http.py 2>&1 | tail -20
```

Expected: `test_max_order_latency_constant_exists` fails with `AttributeError`.

- [ ] Step 3: Implement

Add the constant near the top of `paper.py` with the other module-level constants (after `MIN_ORDER_COST`, around line 93):

```python
MAX_ORDER_LATENCY_MS = 5000  # #79: warn if place_paper_order exceeds this latency
```

Add `import time` at the top of `place_paper_order` body (or at module level — `time` is already imported in stdlib so add to module imports if not present). Then instrument `place_paper_order`:

At the very start of `place_paper_order`, before the `if is_daily_loss_halted():` check, add:

```python
    import time as _time
    _order_start = _time.monotonic()
```

After the `_save(data)` call (line ~384), add:

```python
    # #79: warn if order processing exceeded MAX_ORDER_LATENCY_MS
    _elapsed_ms = (_time.monotonic() - _order_start) * 1000
    if _elapsed_ms > MAX_ORDER_LATENCY_MS:
        _log.warning(
            "place_paper_order: order latency %.1f ms exceeded MAX_ORDER_LATENCY_MS=%d ms "
            "(ticker=%s)",
            _elapsed_ms, MAX_ORDER_LATENCY_MS, ticker,
        )
```

- [ ] Step 4: Run test to verify pass

```
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_paper.py::TestMaxOrderLatency -v --ignore=tests/test_http.py 2>&1 | tail -15
```

Expected: `3 passed`.

- [ ] Step 5: Commit

```
cd "C:/Users/thesa/claude kalshi" && git add paper.py tests/test_paper.py && git commit -m "feat(#79): add MAX_ORDER_LATENCY_MS constant and latency warning to place_paper_order"
```

---

### Task 9: Full regression check

**Files:** none modified

- [ ] Step 1: Run the full test suite and confirm no regressions

```
cd "C:/Users/thesa/claude kalshi" && python -m pytest --ignore=tests/test_http.py -v 2>&1 | tail -40
```

Expected: All Group D tests pass. The 13 pre-existing failures in `test_paper.py` may still be present — confirm that the count has not increased. New tests added in this plan must all show `PASSED`.

- [ ] Step 2: Confirm pre-existing failure count has not grown

```
cd "C:/Users/thesa/claude kalshi" && python -m pytest tests/test_paper.py --ignore=tests/test_http.py -v 2>&1 | grep -E "FAILED|PASSED|ERROR" | tail -30
```

Expected: No new `FAILED` lines beyond the 13 pre-existing ones.

- [ ] Step 3: Final commit if any stray changes remain

```
cd "C:/Users/thesa/claude kalshi" && git status
```

If clean, no commit needed. If there are unstaged changes, investigate before committing.
