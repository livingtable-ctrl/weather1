# Batch 35: weather_markets.py internal correctness + regime sizing

## Context

Repo: weather1. Written 2026-08-23 against master `f4291771` — re-verify before starting. Source: `audit/POST_MERGE_REVIEW.md`. Files owned: `weather_markets.py`, `regime.py`. Parallel-safe with 33/34/36-39. NOTE: batch 40 (between-bracket calibration design) also touches weather_markets.py — it is explicitly sequenced AFTER this batch; do not start it concurrently.

Positive baseline (don't re-do): the audit verified all 10 batch commits' changes are intact in this file, `_metar_lock_in`'s membership/clearance split is correct, and `e44bb551`'s dict migration is complete at all call sites.

## Items

### 1. M-15 [MEDIUM]: `load_member_quarantine_state` fails OPEN on a transient read error

**Files:** `weather_markets.py:3541-3556`. Batches `2315636d`/`6e84e7c2`.
`except Exception: return {}` discards the last-known-good cached state — a mid-`os.replace` read or AV hold re-admits a quarantined ensemble member into the live blend for that call (`ensemble_models_with_ecmwf:4328-4330`), and the empty cache tag misses the prewarmed entry → full per-market refetch; different markets in one scan can be blended from different model sets. Every sibling loader preserves its cache on transient failure with a comment saying why (`_load_platt_models:1264`, `_load_metar_calibration:1311`, `_maybe_refresh_calibration_weights:952`). Mirror that pattern; add a test (existing coverage at `test_main_cron_smoke.py:458` covers only the status log).

### 2. M-16 [MEDIUM]: `_compute_persistence_prob` never received either of the window's two `_metar_lock_in` hardenings

**Files:** `weather_markets.py:6735-6783`. `9eb2f154` touched this exact function and its own resolution note flagged the gap.
(a) AUD-0016 class: uses the live reading only when the daily extreme is None — never the `max()`/`min()` combine its sibling got in `2a0f8e09`. Worked example: cached extreme 86 vs live 91 on "above 88.5" → 0.309 instead of 0.691; persistence carries a fixed 0.15 blend weight on both daily (`:12801`) and hourly (`:10897`) paths → ~5.7pt wrong-side shift.
(b) No per-observation local-date guard on the `_live` fallback (84ce95e6's hoisted guard, `:11048-11093`): at 00:15 local, yesterday's 23:53 reading becomes today's running high.
Also (c) the enclosing bare `except Exception: return None` has no logging — persistence silently drops out of its blend slot; log at WARNING.

### 3. M-17 [MEDIUM]: two prewarm cache-write defects, each already guarded by a sibling path in the same file

**Files:** `weather_markets.py:1801-1807` and `:2206-2246`. Pre-existing.
(a) `batch_prewarm_forecasts` keys the seasonal ECMWF weight off the SCAN date's month (`dates_list[0]` = today) — `get_weather_forecast:1505` and `batch_prewarm_ensemble:2202` both use the target month, and the precip block at `:2165-2172` carries an explicit comment for exactly this hazard. Because prewarm fills the cache first, the wrong-month value is what actually trades across season boundaries (Sep→Oct, Mar→Apr, plus the ENSO term).
(b) `batch_prewarm_ensemble`'s temperature blend writes on `if all_temps:` alone — no "every model contributed" guard (the precip sibling has one at `:2157-2164` with a comment). A circuit-breaker opening mid-loop (the documented expected failure mode, `:1858-1875`) overwrites a complete 3-model blend with a single-model one for a full cycle TTL, indistinguishable in logs. Port both sibling guards.

### 4. M-31 [MEDIUM | skeptic-verified, pre-existing]: regime Kelly boost is climatology-blind and unclamped

**Files:** `regime.py:58,67`; consumers `weather_markets.py:12812`, `:13305`, `:13672`, `:8542-8543`, `:12862`.
Absolute triggers (`mean>95 & std<5` → heat_dome, `mean<25 & std<5` → cold_snap) grant `confidence_boost=1.20` via an UNCLAMPED multiply into `_price_and_size` (bounded only by the final Kelly cap, which observed sizing does not pin). Skeptic verification: Phoenix/Vegas summer KXHIGH sits squarely in the firing band (sigma 3.2-3.5, means >95 routine) — fires on ordinary days; winter cold_snap often disqualified (MSP/CHI winter sigma 7-8.4 > 5); real delta frequently +4.3% vs the `blocking_high` 1.15 fallback, full +20% only in the 3≤std<5 band; `horizon_scale` decays it by days_out=10. Second consumer at `:12862` (blend-weight shift) IS gated by `_regime_blend_active()`; the Kelly boost is gated by nothing. Untouched by any batch, not in backlog.
**Fix direction (AskUserQuestion — genuine design choice):** (a) compare against the city/month climatological normal (climatology.py already caches it) so "unusually hot/cold" means unusual; (b) gate the Kelly boost behind the same settled-count gate the blend shift already has; or (c) neutralize heat_dome/cold_snap to 1.0 pending validation, keeping the spread-only blocking_high. Recommend (a)+(b) together; (c) is the safe minimal.

### 5. L-17 registry-tie [LOW]: `_KXTEMP_HOURLY_CITY` not structurally tied to `KNOWN_WEATHER_SERIES`

**Files:** `weather_markets.py:4664-4677`, `:5120-5126`, `:11699`.
Adding a 6th hourly series to the fetch list alone bypasses BOTH the `_is_hourly` branch (market flows into the daily pipeline incl. `_metar_lock_in` — the contamination hazard `backlog.txt:6766-6769` names) AND the shadow-only routing in order_executor/main (real orders). Registries in sync today (5/5; rain 11/11, snow 1/1); nothing asserts it. Add a guard test asserting every `KXTEMP*H`-prefixed series in `KNOWN_WEATHER_SERIES` is in `_KXTEMP_HOURLY_CITY` (test file lives in this batch's scope even though tests/ is batch 38's theme — it asserts THIS file's invariant).

### 6. LOW/INFO sweep [same file]
(a) `:10462-10464` hurricane next-event `as_of_month_day` UTC vs target ET (`:10477-10488`) — align to ET (shadow-only; 20:00-24:00 ET off-by-one).
(b) `:370` vs `:394-397` `_get_combined_station_bias` docstring contradicts code — fix the docstring.
(c) Dead code: `:12047-12050` no-op `if/pass`; `:10975-10979` unreachable `else` (`prob_threshold` never returns None) — delete or comment; keep `:12444-12462`'s unreachable hourly handling as defense-in-depth (documented decision).
(d) batch-13 follow-through: `batch_prewarm_forecasts` (`:1765-1788`) never calls `validate_forecast` while `get_weather_forecast._fetch_one` (`:1543-1546`) now raises on it — mirror the gate on the path that actually fills the cache in production (mostly covered by open L23595; cite it).

## Process

Full 29-step workflow (live trade-entry pricing surface; opus review effort=high). Re-verify claims live. Scoped tests only: `tests/test_weather_markets.py`, `tests/test_regime.py`, `tests/test_metar.py`, `tests/test_forecasting.py` — **never the full suite**. Lint via the real pre-commit interpreter. Backlog entries + `backlog_index.py`. Confirm before commit. Full workflow: `memory/feedback_implementation_workflow.md`.
