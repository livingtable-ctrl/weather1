# Profit Optimization — Design Spec
**Date:** 2026-04-11  
**Status:** Approved  

---

## Context

The bot currently auto-trades only when edge ≥ 25% AND time_risk is LOW (same-day). With 3 settled trades after weeks of operation, **trade frequency is the primary bottleneck**. Calibration is excellent (Brier 0.0064), P&L gate is cleared (+$89). The 10 changes below are grouped into 4 sections.

---

## Section 1: Trade Frequency

### 1a. Tiered Auto-Trade + MEDIUM-Risk Markets

Replace the binary `STRONG_EDGE` gate with two tiers:

| Tier | Edge | Time Risk | Per-trade cap |
|------|------|-----------|---------------|
| MED | 15–24% | LOW or MEDIUM | $20 |
| STRONG | 25%+ | any | $50 (base; dynamic in §2) |

**Files:**
- `utils.py` — add `MED_EDGE = float(os.getenv("MED_EDGE", "0.15"))`
- `paper.py` — `kelly_bet_dollars(kelly_fraction, cap=50.0)` gains `cap` parameter; hard cap becomes `min(dollars, cap)`
- `main.py` — `cmd_cron` builds two lists (`med_opps`, `strong_opps`); calls `_auto_place_trades()` for both with their respective caps

MEDIUM risk = next-day markets, already labeled by `_time_risk()`.

### 1b. NWP Cycle-Aligned Scanning

Model data is freshest at 02, 08, 14, 20 UTC (2h after each NWP run). Market prices are slowest to update immediately after a new model cycle.

**Files:**
- `main.py` — add `cmd_schedule_cycles()` that prints four `schtasks /Create` commands for 02:15, 08:15, 14:15, 20:15 UTC
- `_ttl_until_next_cycle()` already exists in `weather_markets.py` and is used for cache TTL; no change needed there

---

## Section 2: Position Sizing

### 2a. Dynamic Cap Based on Brier Score

As Brier improves the STRONG-tier cap unlocks automatically:

| Brier score | STRONG cap |
|-------------|------------|
| > 0.15 | $50 |
| ≤ 0.15 | $75 |
| ≤ 0.10 | $100 |
| ≤ 0.05 | $125 |

At current Brier of 0.0064, STRONG trades immediately unlock the $125 cap.

**Files:**
- `paper.py` — `kelly_bet_dollars()` calls `brier_score()` (already imported from tracker) to determine dynamic cap before applying the tier cap passed by caller. MED-tier cap ($20) always wins over dynamic cap for medium-edge trades.

### 2b. Condition-Type Brier Up-Weighting

`brier_score_by_method()` already exists in `tracker.py`. Use it to scale Kelly per condition type:

| Condition Brier | Kelly multiplier |
|-----------------|-----------------|
| ≤ 0.10 | 1.0× |
| > 0.20 | 0.75× |
| insufficient data (< 5 trades) | 1.0× (no change) |

**Files:**
- `paper.py` — `kelly_bet_dollars(kelly_fraction, cap=50.0, condition_type=None)` gains `condition_type` param; applies multiplier before cap
- `main.py` — `_auto_place_trades()` passes `condition_type` from the analysis dict to `place_paper_order()`, which passes it to `kelly_bet_dollars()`

---

## Section 3: Signal Quality

### 3a. Model Consensus Gate

Before blending ICON and GFS into a single `ens_prob`, check if they agree.

- Compute `icon_prob` and `gfs_prob` separately in `analyze_trade()` using the already-fetched ensemble temps split by model
- If `abs(icon_prob - gfs_prob) > 0.08`, set `model_consensus: False` on the result dict
- In `_auto_place_trades()`, apply 0.5× Kelly multiplier when `model_consensus: False` (still trades, just smaller)
- Fallback: if either model returned no data, `model_consensus` is omitted (treated as True)

**Files:**
- `weather_markets.py` — `analyze_trade()` adds consensus check and `model_consensus` field
- `main.py` — `_auto_place_trades()` reads `model_consensus` and halves Kelly when False

### 3b. Near-Threshold Detection

Markets where the strike is within 3°F of the forecast temp are frequently mispriced — the market anchors near 50/50 but our ensemble has directional signal.

- In `analyze_trade()`, compute `threshold_distance = abs(forecast_temp - condition["threshold"])`
- If `threshold_distance ≤ 3.0` AND `abs(edge) >= MIN_EDGE`, set `near_threshold: True`
- Dashboard signals cache includes this flag; `stars` field or a new `flags` list surfaces it visually
- No sizing change — data collection only until we have 30+ trades to validate the pattern

**Files:**
- `weather_markets.py` — `analyze_trade()` adds `near_threshold` field
- `main.py` — `cmd_cron` includes `near_threshold` in signals cache entry

---

## Section 4: Trade Management

### 4a. Early Exit on Model Cycle Update

Each cron run, re-analyze open positions. Close early if updated probability shifts >15pp against entry direction.

- Load open positions via `get_open_trades()` from `paper.py`
- Re-run `analyze_trade()` for each open ticker
- If `abs(current_prob - entry_prob) > 0.15` and direction has flipped against position, call `close_paper_early(trade_id, current_price)`
- Log early exit with reason `"model_update"` to cron.log

**Files:**
- `paper.py` — add `close_paper_early(trade_id: int, exit_price: float)` which settles the trade at `exit_price` rather than $0/$1, computing P&L as `(exit_price - entry_price) * quantity` (for YES side); marks trade settled with `outcome: "early_exit"`
- `main.py` — `cmd_cron` adds a re-analysis loop after the main scan; fetches current market price via `_midpoint_price()` and calls `close_paper_early()` on trigger

### 4b. Daily Spend Cap

Prevents over-concentration on a bad-forecast day.

- New const `MAX_DAILY_SPEND = float(os.getenv("MAX_DAILY_SPEND", "100.0"))` in `utils.py`
- In `_auto_place_trades()`, sum `entry_price * quantity` for today's paper trades before placing each new one
- If cumulative spend ≥ cap, skip and log `"daily cap reached"` to cron.log
- Cap applies to MED + STRONG combined

**Files:**
- `utils.py` — `MAX_DAILY_SPEND` const
- `main.py` — `_auto_place_trades()` checks daily spend before each placement

### 4c. Entry Hour Tracking

Lays groundwork for future entry-timing optimization. No behavioral change yet.

- Add `entry_hour` (UTC int 0–23) to each paper trade record written by `place_paper_order()`
- After 30+ trades, a new analytics command can group by hour and surface the best windows

**Files:**
- `paper.py` — `place_paper_order()` adds `entry_hour: datetime.now(UTC).hour` to the trade dict before writing

---

## Summary of File Changes

| File | Changes |
|------|---------|
| `utils.py` | Add `MED_EDGE`, `MAX_DAILY_SPEND` |
| `paper.py` | `kelly_bet_dollars()` gains `cap`, `condition_type` params + dynamic Brier cap; `place_paper_order()` records `entry_hour`; add `close_paper_early()` |
| `weather_markets.py` | `analyze_trade()` adds `model_consensus`, `near_threshold` fields; splits ICON/GFS probs before blending |
| `main.py` | `cmd_cron` builds MED+STRONG tiers, daily spend check, early-exit loop, near_threshold in cache; add `cmd_schedule_cycles()` |

---

## What's Not Changing

- Graduation criteria (30 trades, $50 P&L, Brier ≤ 0.20)
- Half-Kelly formula and 33% bankroll hard cap
- Spread gate, liquidity gate, MAX_DAYS_OUT gate
- All existing drawdown tiers and streak pause logic
