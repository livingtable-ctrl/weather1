# Accuracy Improvement Plan v2 — 2026-04-19

Full inventory of every accuracy gap found across two deep audit passes.
Items ordered within each tier by expected P&L impact.
Status: ⬜ = not started · 🔄 = in progress · ✅ = done

---

## Previously completed (plan v1 — all 24 items done)

| Item | Title | Files |
|------|-------|-------|
| A1 ✅ | Wire `apply_ml_prob_correction()` into `analyze_trade` | `weather_markets.py`, `ml_bias.py` |
| A2 ✅ | Call `record_feature_contribution()` on every trade placed | `main.py`, `feature_importance.py` |
| A3 ✅ | Call `update_outcome()` on every trade settled | `main.py`, `feature_importance.py` |
| A4 ✅ | Auto-place consistency arbitrage trades (not just display) | `main.py`, `consistency.py` |
| A5 ✅ | Feed param-sweep optimal `PAPER_MIN_EDGE` back to config | `param_sweep.py`, `config.py` |
| B1 ✅ | MOS uses wrong sigma — replace with MOS-specific RMSE | `weather_markets.py`, `mos.py` |
| B2 ✅ | Fetch NAM-MOS in addition to GFS-MOS; prefer NAM days_out ≤ 1 | `mos.py`, `weather_markets.py` |
| B3 ✅ | Add Denver (KDEN) to MOS station list | `mos.py` |
| B4 ✅ | Split station bias by HIGH vs LOW market | `weather_markets.py` |
| B5 ✅ | Relax `get_bias()` stale-data cutoff 14 → 60 days | `tracker.py` |
| B6 ✅ | Move MOS blend to before bias correction | `weather_markets.py` |
| B7 ✅ | Use `ens_stats["std"]` as Gaussian sigma when available | `weather_markets.py` |
| C1 ✅ | Tighten `MAX_MODEL_SPREAD_F` 8.0 → 5.5 °F | `.env` |
| C2 ✅ | Require all 3 sources for consensus bonus | `weather_markets.py` |
| C3 ✅ | Hard-skip trades when regime is "volatile" (std > 12 °F) | `weather_markets.py` |
| C4 ✅ | Reduce `MAX_DAYS_OUT` 5 → 2 | `.env` |
| C5 ✅ | Reduce calibration grid step 5 % → 1 % | `calibration.py` |
| C6 ✅ | Add `ABTest` for `MIN_EDGE` variants 0.05 / 0.07 / 0.09 | `main.py`, `ab_test.py` |
| D1 ✅ | Give ECMWF 2× weight in `model_temps` Gaussian blend | `weather_markets.py` |
| D2 ✅ | Add winter / summer sigma split to `_HISTORICAL_SIGMA` | `weather_markets.py` |
| D3 ✅ | Fix persistence baseline: use today's observed max, not current temp | `weather_markets.py` |
| D4 ✅ | Feed walk-forward optimal params back to config | `backtest.py`, `config.py` |
| D5 ✅ | Add `train-bias` to weekly cron (Sun 02:00 UTC) | `cron.py` |
| D6 ✅ | Lower calibration minimum samples: 50 → 20 seasonal, 30 → 15 city | `calibration.py` |

---

## Phase E — High impact: probability pipeline calibration

| # | Status | Title | File(s) |
|---|--------|-------|---------|
| E1 | ⬜ | Per-quintile bias correction (replace global offset) | `tracker.py`, `weather_markets.py` |
| E2 | ⬜ | Blend Gaussian with ensemble instead of fallback-only | `weather_markets.py` |
| E3 | ⬜ | Scale Kelly by CI width (not just point estimate) | `weather_markets.py` |
| E4 | ⬜ | Validate NWS temp observation before feeding to CDF | `nws.py` |
| E5 | ⬜ | Reduce NWS blend weight when NWS diverges from ensemble | `weather_markets.py` |

### E1 — Per-quintile bias correction

**Problem:** `get_bias()` returns a single scalar applied uniformly across all probability
ranges. A +0.05 offset is correct at p=0.75 but wrong at p=0.50 (where calibration is
most important and trade count is highest). The global mean hides opposite-direction errors
in different probability buckets.

**Fix:** In `tracker.py` → `get_bias()`, bin settled trades into 5 probability quintiles
(0–0.20, 0.20–0.40, 0.40–0.60, 0.60–0.80, 0.80–1.0) and compute a separate mean error
per bin. In `weather_markets.py`, after computing `blended_prob`, select the quintile bin
and apply that bin's offset. Fall back to the global offset when a bin has fewer than
5 samples.

This is isotonic regression / Platt-scaling lite. No new dependencies required.

**Expected impact:** +0.03–0.05 Brier score improvement. Largest single gain available.

---

### E2 — Gaussian blend alongside ensemble, not only as fallback

**Problem:** At [weather_markets.py:3281](weather_markets.py):
```python
# Only use Gaussian blend when large ensemble didn't produce a result
if ens_prob is None:
    ens_prob = gaussian_blend
```
`gaussian_blend` (Gaussian CDF around forecast_mean) is computed but discarded whenever
the ensemble produces a result. The ensemble fraction is a raw member count that can be
noisy with small or skewed member distributions. Blending 30 % Gaussian with 70 % ensemble
smooths this without discarding either signal.

**Fix:** Replace the `if ens_prob is None` guard with an unconditional blend when both
signals are available:
```python
if ens_prob is not None and gaussian_blend is not None:
    # 70 % ensemble fraction, 30 % Gaussian — ensemble dominates but Gaussian smooths
    ens_prob = 0.70 * ens_prob + 0.30 * gaussian_blend
elif ens_prob is None and gaussian_blend is not None:
    ens_prob = gaussian_blend
```

**Expected impact:** +0.01–0.02 Brier. Prevents ensemble noise from propagating directly
into the final blend at the highest weight.

---

### E3 — Use CI width to scale Kelly fraction

**Problem:** Kelly is sized from the point-estimate probability alone. A trade with CI
[0.55, 0.65] (narrow, high confidence) and one with CI [0.40, 0.80] (wide, speculative)
get the same Kelly if their midpoints agree. The CI is computed (via bootstrap or 2-sigma)
but is only shown in the UI; it never reaches position sizing.

**Fix:** In `analyze_trade()`, after the CI is computed, derive a `ci_scale` factor:
```python
ci_width = ci_high - ci_low          # e.g. 0.10 for tight, 0.40 for wide
ci_scale = max(0.25, 1.0 - ci_width * 2.0)   # 0.10 → 0.80, 0.40 → 0.20
ci_adjusted_kelly = fee_kelly * ci_scale
```
Store `ci_scale` in the analysis dict for transparency.

**Expected impact:** Primary drawdown reduction; secondary +0.01–0.02 Brier from avoiding
over-bet losses on speculative trades.

---

### E4 — Validate NWS temperature observation before CDF input

**Problem:** `nws.py` passes `obs["temp_f"]` directly to `normal_cdf` without range
validation. A malformed or null NWS response propagates `NaN` into the same-day market's
0.95-weighted observation override, silently corrupting that trade's probability.

**Fix:** In `nws.py`, add before probability computation:
```python
if temp_f is None or not (-60.0 <= float(temp_f) <= 130.0):
    return None
```
`analyze_trade` already handles `None` from the NWS path gracefully.

**Expected impact:** Prevents silent NaN corruption on same-day markets. No normal-weather
effect; prevents black-swan errors during API anomalies.

---

### E5 — Reduce NWS weight when it diverges from ensemble

**Problem:** NWS hourly forecasts lag model runs by up to 24 hours during rapidly evolving
weather. The blend applies NWS at ~0.30 weight regardless of divergence from the ensemble.
In ~15 % of markets (pattern changes, convective events), NWS is 0.20+ probability units
away from ensemble consensus.

**Fix:** After computing `nws_prob` and `ens_prob`, check divergence:
```python
if abs(nws_prob - ens_prob) > 0.20:
    w_nws = 0.10   # NWS is likely stale; demote
    _log.debug("NWS demoted (divergence %.2f) for %s", abs(nws_prob - ens_prob), ticker)
else:
    w_nws = 0.30   # normal weight
```
Renormalize remaining blend weights accordingly.

**Expected impact:** +0.01–0.02 Brier on the ~15 % of markets where NWS lags.

---

## Phase F — Medium impact: signal and sizing fixes

| # | Status | Title | File(s) |
|---|--------|-------|---------|
| F1 | ⬜ | Scale same-day obs weight by hour (not flat 0.95) | `weather_markets.py` |
| F2 | ⬜ | Apply consensus Kelly bonus before the 0.25 cap | `weather_markets.py` |
| F3 | ⬜ | Auto-trigger calibration every 25 new settled trades | `calibration.py`, `cron.py` |
| F4 | ⬜ | Fix race condition in `feature_importance.update_outcome()` | `feature_importance.py` |
| F5 | ⬜ | Skip markets where both bid and ask are zero | `weather_markets.py` |
| F6 | ⬜ | Raise Cholesky positive-definite threshold 1e-12 → 1e-8 | `monte_carlo.py` |
| F7 | ⬜ | Break A/B test ties randomly, not alphabetically | `ab_test.py` |
| F8 | ⬜ | Use tracker-derived weights in Gaussian fallback path | `weather_markets.py` |

### F1 — Hour-dependent same-day observation weight

**Problem:** Same-day markets apply a flat 0.95 weight to live METAR regardless of time.
At 08:00 the daily high can still rise 10 °F; the current reading is a floor, not the
outcome. Locking in 95 % weight at 08:00 creates systematic errors on warming days.

**Fix:**
```python
if days_out == 0 and obs_temp is not None:
    hour = datetime.now(tz).hour
    obs_weight = min(0.95, 0.55 + hour / 24.0 * 0.40)
    blended_prob = obs_weight * obs_override + (1 - obs_weight) * blended_prob
```
At 08:00 → weight 0.68; at 14:00 → weight 0.78; at 18:00 → weight 0.85.

**Expected impact:** Reduces same-day systematic error on trend days. ~0.01 Brier.

---

### F2 — Consensus Kelly bonus applied before cap

**Problem:** The 1.25× Kelly bonus for 3-source consensus fires after the 0.25 cap. Any
trade at Kelly ≥ 0.20 gets `min(0.25×1.25, 0.25) = 0.25` — the bonus is a no-op. The
strongest signals are sized identically to borderline signals.

**Fix:** Move the consensus multiplication before the cap and raise the consensus ceiling:
```python
if model_consensus:
    fee_kelly = min(fee_kelly * 1.25, 0.33)   # 0.33 cap for consensus trades
else:
    fee_kelly = min(fee_kelly, 0.25)
```

**Expected impact:** Unlocks proper sizing for highest-conviction trades. ~0.01 Brier.

---

### F3 — Auto-trigger calibration every 25 settled trades

**Problem:** `calibrate_seasonal_weights()` and `calibrate_city_weights()` are called only
via `py main.py calibrate`. Weights become stale as trades accumulate and at seasonal
boundaries.

**Fix:** In `cron.py`, track the settled trade count. When it has increased by 25 since
the last calibration run, call both calibration functions automatically. Alternatively,
add a weekly Sunday 03:00 UTC job alongside the existing `train-bias` job.

**Expected impact:** Prevents weight decay between manual runs. ~0.01 Brier per season.

---

### F4 — Atomic write in `feature_importance.update_outcome()`

**Problem:** `update_outcome()` reads the full JSONL file, modifies one entry, and writes
the whole file. Two concurrent settlements (cron + manual) race: last write wins,
silently losing one outcome record.

**Fix:** Use a file lock or switch to append-only writes with periodic compaction:
```python
# append-only version
with open(path, "a") as f:
    f.write(json.dumps({"ticker": ticker, "won": won, "ts": time.time()}) + "\n")
```
On read, de-duplicate by ticker keeping the latest record.

**Expected impact:** Prevents silent data loss in `feature_importance` which feeds ML bias
training. No direct Brier impact but protects downstream models.

---

### F5 — Skip markets where both bid and ask are zero

**Problem:** `parse_market_price()` returns `implied_prob = 0.0` when both `yes_bid` and
`yes_ask` are zero. This propagates into `find_violations()` as a real "0 % chance"
implied probability and can trigger spurious arbitrage alerts.

**Fix:** In `parse_market_price()`, after computing `mid`:
```python
if mid <= 0:
    return {**result, "implied_prob": 0.0, "has_quote": False}
```
In `find_violations()`, skip entries where `implied_prob == 0 and not has_quote`.

**Expected impact:** Eliminates false arbitrage signals. No Brier effect; prevents bad trades.

---

### F6 — Raise Cholesky threshold to tolerate floating-point noise

**Problem:** `monte_carlo._cholesky()` returns `None` (falls back to independent draws)
when any eigenvalue is ≤ 1e-12. Empirical correlation matrices computed from small samples
routinely have near-zero eigenvalues from floating-point noise, not true singularity. The
silent fallback to independent draws over-diversifies the portfolio Kelly estimate.

**Fix:**
```python
if v <= 1e-8:   # was 1e-12
    return None
```
Or use `numpy.linalg.lstsq` / pseudo-inverse when the matrix is nearly singular.

**Expected impact:** Portfolio Kelly sizes more accurately reflect correlations. Secondary
benefit: Monte Carlo VaR estimates are more realistic.

---

### F7 — Break A/B test ties with random selection

**Problem:** `ABTest.pick_variant()` uses `min(..., key=lambda v: trades_count)`. When two
variants are tied, Python's `min()` returns the first in iteration order (effectively
alphabetical for dicts). "control" is always prioritized over "variant_b" when tied,
biasing the test in the early phase.

**Fix:**
```python
min_trades = min(self._state[v]["trades"] for v in active)
tied = [v for v in active if self._state[v]["trades"] == min_trades]
chosen = random.choice(tied)
```

**Expected impact:** Removes selection bias in early A/B test. Ensures statistical validity.

---

### F8 — Use tracker-derived model weights in Gaussian fallback path

**Problem:** When `ens_prob is None` (ensemble failed), `raw_fraction` is computed using
the hardcoded `{"nbm": 1.0, "ecmwf": 2.0}` weights (line 3251). The tracker's live
`_dynamic_model_weights()` (which uses recent MAE per model) is not consulted on this
code path, making the fallback inconsistent with the normal path.

**Fix:** In the Gaussian fallback section, call `_dynamic_model_weights(city, month)` and
use the returned dict for `raw_fraction` computation, falling back to `_model_weights_d1`
if the tracker returns None.

**Expected impact:** ~0.005–0.01 Brier on the minority of trades that hit the Gaussian path.

---

## Phase G — Lower impact: reliability and edge cases

| # | Status | Title | File(s) |
|---|--------|-------|---------|
| G1 | ⬜ | Log and renormalize when climatology returns None | `weather_markets.py` |
| G2 | ⬜ | Spread gate should check `low_range` for LOW markets | `weather_markets.py` |
| G3 | ⬜ | Raise or warn on `fsync` failure in `atomic_write_json` | `safe_io.py` |
| G4 | ⬜ | Fix tracker unique index to handle timezone edge case | `tracker.py` |
| G5 | ⬜ | Schedule `run_sweep()` weekly in cron | `cron.py` |
| G6 | ⬜ | Align cache TTL to monotonic time throughout | `forecast_cache.py`, `weather_markets.py` |
| G7 | ⬜ | Log summary when all notification channels fail | `notify.py` |

### G1 — Renormalize blend when climatology is unavailable

**Problem:** When `climatological_prob()` returns `None` (fewer than 30 samples in the
calendar window), the blend weight `w_clim` is applied to `None`. This silently zeroes out
the climatology contribution without renormalizing the remaining `w_ens + w_nws` weights.
The blend no longer sums to 1.0.

**Fix:** After each source is fetched, check for `None` and redistribute its weight
proportionally to the remaining sources. Log at DEBUG when a source is skipped.

---

### G2 — Model spread gate must check `low_range` for LOW markets

**Problem:** The spread gate at weather_markets.py ~line 3165 checks `_high_range`
(spread in daily-high forecasts) regardless of whether the market is for daily HIGH or
daily LOW. For LOW markets, `_low_range` is the relevant disagreement metric.

**Fix:**
```python
spread_range = _low_range if var == "min" else _high_range
if spread_range is not None and spread_range > MAX_MODEL_SPREAD_F:
    return None
```

---

### G3 — Raise WARNING on fsync failure in `atomic_write_json`

**Problem:** `safe_io.atomic_write_json()` catches `OSError` on `fsync` at `log.debug`
level and proceeds to rename the temp file without confirmed durability. On a stressed
system this silently loses trade ledger data.

**Fix:** Change the except to log at `WARNING` and either retry fsync once or raise
so the caller can decide whether to proceed.

---

### G4 — Tracker prediction index: explicit date column

**Problem:** The UPSERT unique index uses `date(predicted_at)` (SQLite function) on a
timestamp column. Two rows at 23:58 UTC and 00:02 UTC on consecutive calendar days in
the same timezone map to different dates, but the same pair in different timezones could
map to the same date. Low probability but silent data loss when it occurs.

**Fix:** Add an explicit `predicted_date TEXT` column populated at insert time as
`date.today().isoformat()`. Index on `(ticker, predicted_date)`.

---

### G5 — Schedule `run_sweep()` weekly in cron

**Problem:** A5 (done) wires `param_sweep_results.json` into `config.py` as a soft
override, but `run_sweep()` is still only called manually via `py main.py sweep`.
If the results file is absent or stale, the entire A5 feedback loop is dormant.

**Fix:** Add to `cron.py` Sunday schedule:
```python
schedule.every().sunday.at("03:30").do(run_sweep)
```
Runs after `train-bias` (02:00) so the new bias model is trained before sweep evaluates it.

---

### G6 — Align cache TTL to monotonic time

**Problem:** `ForecastCache` uses `time.monotonic()` for TTL expiry, but
`weather_markets.py` estimates cache age using wall-clock subtraction when loading from
disk. An NTP correction or daylight-saving jump makes these inconsistent, causing either
premature or delayed cache expiry.

**Fix:** Store `time.time()` (wall-clock) alongside the cached value and compare on load
consistently, or use monotonic time exclusively within a single process lifetime without
persisting it.

---

### G7 — Log aggregate notification failure

**Problem:** `alert_strong_signal()` in `notify.py` tries up to 5 channels independently.
If all fail, no summary is written. A strong edge signal that should have triggered an
alert passes silently.

**Fix:** Collect per-channel success/failure and after all attempts:
```python
if not any(successes):
    _log.warning("alert_strong_signal: all channels failed for %s", ticker)
```

---

## Implementation order

```
Phase E (highest Brier impact)
  E1 → E2 → E3 → E4 → E5

Phase F (medium impact, mostly one-liners)
  F2 → F1 → F5 → F7 → F3 → F6 → F4 → F8

Phase G (reliability)
  G3 → G1 → G2 → G5 → G4 → G6 → G7
```

Start with **E1** (per-quintile bias) — it's the single largest expected gain.
Then **E2** (Gaussian blend) and **E3** (CI-width Kelly) together since they touch the same
section of `analyze_trade()`. The Phase F items are all small and can be batched into a
single commit.

---

## Expected impact summary

| Phase | Items | Combined Brier gain | Mechanism |
|-------|-------|---------------------|-----------|
| E — Calibration | 5 | +0.06–0.10 | Better probability estimates before sizing |
| F — Sizing / signals | 8 | +0.02–0.05 | Correct sizing and signal weighting |
| G — Reliability | 7 | Indirect | Prevents silent data loss and bad trades |

**Total new items: 20** across 3 phases.
**Grand total across both plans: 44 items.**
