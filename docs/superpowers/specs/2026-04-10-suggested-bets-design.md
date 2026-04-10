# Suggested Bets + Risk Tolerance Design

**Date:** 2026-04-10  
**Goal:** Surface Kelly-sized bet recommendations on the `/analyze` page and loosen risk thresholds to capture more profitable opportunities.

---

## Problem

The `/analyze` page shows market opportunities with edge % and a YES/NO signal but gives no guidance on how much to bet. Users must manually calculate Kelly dollars from the raw fraction. The minimum edge threshold (10%) and Kelly cap (25%) are also more conservative than necessary for a profit-focused strategy.

---

## Architecture

Three targeted changes across three files — no new files created.

### 1. `weather_markets.py` — raise Kelly cap

In `kelly_fraction()`, change the hard cap:

```python
# Before
return min(half_kelly, 0.25)

# After
return min(half_kelly, 0.33)
```

This allows up to 33% of bankroll per trade (up from 25%). All existing drawdown scaling, portfolio limits, and correlation penalties still apply on top of this.

### 2. `web_app.py` — new `/api/suggested_bets` endpoint + lower MIN_EDGE default

**MIN_EDGE default:** `0.10` → `0.07`. Kalshi fees eat ~2%, so 7% net edge is still real positive EV. Going below 5% would be noise.

**New endpoint:** `GET /api/suggested_bets?n=3`

Logic:
1. Fetch active markets (same source as `/analyze`)
2. Run each through `analyze_trade()` pipeline
3. Filter: `net_edge >= MIN_EDGE` (0.07)
4. Compute `kelly_dollars = kelly_fraction × current_balance`
5. Compute `ev_score = net_edge × kelly_dollars` (ranking key, not displayed)
6. Return top-N sorted by `ev_score` descending

Response shape:
```json
{
  "bets": [
    {
      "ticker": "KXHIGHNY-26APR15-T68",
      "title": "NYC High Temp above 68°F on Apr 15",
      "city": "NYC",
      "recommended_side": "YES",
      "edge_pct": 14.2,
      "kelly_fraction": 0.18,
      "suggested_dollars": 12.60,
      "signal": "BUY YES",
      "ev_score": 1.79
    }
  ],
  "balance": 70.00,
  "min_edge": 0.07,
  "generated_at": "2026-04-10T14:32:00"
}
```

### 3. `/analyze` template — two frontend additions

**A. Pinned "Today's Top Bets" card** at the top of the page. Fetches `/api/suggested_bets` on load. Displays up to 3 rows: rank (#1/#2/#3), ticker, title, side badge (YES/NO), edge %, and a prominent "Bet $X.XX" amount. Shows a loading state while fetching, and a "No strong bets today" message if the list is empty.

**B. "Suggested Bet" column** added to the existing analyze table. Populated from the same `/api/suggested_bets` response — matches by ticker. Rows not in the top-3 still show their Kelly dollar amount if they're above the edge threshold (all above-threshold opportunities get a dollar figure, not just the top 3).

---

## Risk Constant Summary

| Parameter | Before | After | Rationale |
|-----------|--------|-------|-----------|
| `MIN_EDGE` default | 10% | 7% | Captures real-EV trades above fee floor |
| Kelly cap per trade | 25% | 33% | More aggressive while keeping portfolio limits |
| Drawdown scaling | unchanged | unchanged | Protective — don't touch |
| Portfolio limits | unchanged | unchanged | City/date/directional caps stay |

---

## Testing

**`tests/test_weather_markets.py`** — append one test to verify the new Kelly cap:
```python
def test_kelly_fraction_caps_at_33_pct():
    # Very high edge scenario that would exceed 33% without cap
    result = kelly_fraction(our_prob=0.95, price=0.10, fee_rate=0.02)
    assert result == pytest.approx(0.33, abs=1e-6)
```

**`tests/test_suggested_bets.py`** (new file) — two tests:
1. Ranking test: given 5 mocked `analyze_trade()` results with known edges and Kelly fractions, endpoint returns top 3 sorted by EV (edge × kelly_dollars)
2. Empty test: when no opportunities exceed `MIN_EDGE`, endpoint returns `{"bets": [], ...}`

---

## Out of Scope

- Auto-placing bets (one-click order submission) — manual execution only for now
- Push notifications with top-3 — existing `alert_strong_signal()` is separate
- Changing `fixed_pct` or `fixed_dollars` strategy behavior
