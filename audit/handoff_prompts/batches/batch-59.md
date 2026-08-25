# Batch 59: METAR / settlement correctness (HIGH — contains the OKC/SATX incident's live root cause)

## Context

Repo: weather1. Written 2026-08-24 against master `223dedadcfd2` — re-verify current before starting. Source: backlog.txt L26930, L27010, L4873, L24945 (re-verified against live code during batch-48's backlog sweep, 2026-08-24).

Files owned: `weather_markets.py` (the `_metar_lock_in` / hurricane-signal / `model_consensus` regions), `settlement_monitor.py`, `order_executor.py` (the Kelly-halving consensus read only). Parallel-safe with 57-58, 60-62 — but see the note below if batches 51/52 or 54/55 are in flight, since those also touch `weather_markets.py`'s registry region.

**Item 1 is the highest-severity item in the entire remaining backlog.** It is the still-live core of a real incident. Do it first, and do not batch it behind the others if time is short.

## Items

### 1. No HIGH-market monotonic-safety veto in `_metar_lock_in` [L26930] ⚠️

**Files:** `weather_markets.py:12255` — `if _is_low_mkt and _lockout.get("locked"):`

The veto block at `:12255-12276` rejects an unsafe lock-in **only for LOW markets**. Its own comment explains the reasoning: a running daily-minimum-so-far can only decrease as the day progresses, so a "locked" verdict at 2pm can be invalidated by later cooling.

The exact symmetric hazard exists for HIGH markets and has no veto: a running daily-**maximum**-so-far at 14:00-15:00, before the day's true peak has occurred, can read as confidently "locked" while the real high is still hours away. **This is the OKC/SATX incident's core shape**, and it remains fully reachable with entirely legitimate, correctly-dated same-day data — i.e. every other guard in the chain passes.

**Fix:** add the HIGH-market equivalent veto. The LOW branch is the template — mirror its structure and its clearance logic, inverted. Do **not** generalize both into one branch without care: the two directions have different diurnal timing (afternoon max vs. overnight/dawn min), so a single shared threshold is likely wrong for one of them. Verify the hour-of-day boundary you pick against real settled data, not intuition.

**This changes live trade-entry probability on same-day markets.** Full ceremony, no shortcuts. Mutation-test the veto specifically: construct the incident's own shape (running max well inside "not yet confirmed" territory at 14:00) and confirm the trade is now rejected where it previously locked.

### 2. `check_city_settlement` never checks the market's own event date [L27010]

**Files:** `settlement_monitor.py:409-585` (`check_city_settlement`), obs-date guard at `:466`, per-market loop at `:477`, upstream ticker build at `:660-724`

The function guards only that the **METAR observation** is from today (`:466`). It never parses the **market's own** date token to confirm the market is a today-settling market. The upstream `active_tickers` build filters only on `status == "open"` — so the entry's own "verify whether the caller filters upstream" question resolves to **no**, it does not.

**Consequence:** a market whose event date is not today can be evaluated against today's observation.

**Fix:** parse the ticker's date segment and require it to match the observation's local date before settling. `weather_markets.parse_city_date()` already does this parsing — reuse it rather than writing a second parser (and note it early-returns `(None, None)` for hurricane-next-event series, which is correct behavior to preserve, not a bug to route around).

### 3. Hurricane `occurred_this_season` is season-scoped, not issuance-scoped [L4873]

**Files:** `weather_markets.py:11476-11487`

Derives `occurred_this_season` purely from `_get_cached_hurricane_count_to_date(basin, year) >= 1`, with no `open_time`/issuance anchoring anywhere. Kalshi confirms these markets roll over — so a market issued *after* a storm already occurred inherits a signal that treats that storm as predictive of the market's own window.

**Currently dormant:** hurricane families are shadow-gated (`HURRICANE_TRADING_ENABLED` unset), and `data/hurricane_count_to_date.json` shows ATL count 0 as of 2026-08-24, so the revisit trigger has not fired.

**Fix:** anchor the signal to the market's own issuance/open time rather than the calendar season. **Because it is dormant, this is the one item here that is legitimately deferrable** — if the batch is running long, drop this and say so rather than rushing items 1-2. But if you do implement it, it still gets full ceremony (it is a trade-entry signal, dormant or not).

### 4. `model_consensus` ignores a quarantined ensemble member [L24945]

**Files:** `weather_markets.py:13760-13761` (`if abs(icon_p - gfs_p) > 0.12: model_consensus = False`), consumer `order_executor.py:4384` (`consensus_mult = 0.5 if not a.get("model_consensus", True)`)

The consensus check still compares icon vs gfs regardless of whether either has been quarantined. `weather_markets.py:3711` carries a code comment explicitly acknowledging this ("still compares icon/gfs regardless of quarantine").

**Consequence:** a quarantined (known-bad) model can drive `model_consensus = False`, which halves Kelly sizing via `:4384` — so a model the system has already decided not to trust still shrinks position sizes.

**Fix:** exclude quarantined members from the consensus comparison. `weather_markets.py:2138` already filters `blend_models` by quarantine — reuse that same source of truth.

**Adjacent, deliberately NOT in this batch:** L24981 (quarantine shifts the blend's spread, but EMOS / anomaly / bimodal guards are fit on the unfiltered 3-model blend) is the calibration-side half of this. It belongs to the calibration/ML cluster, which the project's standing order puts last. Do not stretch this batch to cover it — but do check that your fix here does not make L24981 worse, and note the interaction in the resolution.

## Process

Full 29-step workflow. **No LOW-tier downgrade** — items 1, 3, 4 all change live trade-entry probability or sizing. Opus review at `effort: high`.

**Item 1 warrants its own dedicated review pass** even if the rest share one. It is a safety veto on the exact shape of a real past incident; a reviewer scanning four items will not give it the scrutiny it needs.

Tests: scope to `tests/test_weather_markets*.py`, `tests/test_settlement_monitor.py`, `tests/test_metar*.py`, plus a grep of `tests/` for `_metar_lock_in`, `model_consensus`, and `check_city_settlement` before finalizing. **Never run the bare full suite.**

Every fix mutation-tested individually via genuine Edit-revert-run-restore cycles — not a `python -c` string-replace script, which can silently no-op on a quoting mismatch and leave you believing a mutation was applied.

Timezone discipline: this batch is dense with UTC-vs-city-local hazards (that family already has 5+ recorded instances in this repo). Verify each code path's own `datetime.now()` timezone argument by grepping it directly; do not assume one convention holds file-wide.

Lint via the real pre-commit hook. Update all 4 backlog resolutions, run `python backlog_index.py`, confirm before committing.
