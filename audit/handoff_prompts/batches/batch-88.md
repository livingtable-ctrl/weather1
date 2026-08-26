# Batch 88: the ensemble blend applies its weights per-member, not per-model (direction-entry option 7)

## Context

Repo: weather1. Written 2026-08-26 against master `0d69c25d` — **re-verify current before starting**. Live trading dormant.

**Files owned: `weather_markets.py`.**
**Read-only: `ml_bias.py`, `calibration.py`, `tracker.py` — batch 87 owns them.**

This is option 7 of `backlog.txt`'s *"PROJECT DIRECTION AFTER THE NO-EDGE RESULT"*, and its own entry *"gfs_seamless HAS ~2x THE ERROR OF ITS PEERS ON max..."*. **Step 1 of that entry's plan is already done — the diagnosis below is the result. Start from it.**

## CORRECTIONS 2026-08-26 — TWO ROUNDS. Read both; the first correction was also wrong.

**Round 1 (the original file): wrong blend membership.** This file first named the blend as `gfs_seamless` / `ecmwf_ifs025` / `icon_seamless`. `get_ensemble_temps` (`:5467`) iterates `_QUARANTINE_CANDIDATE_MODELS` (`:4611`) = `("icon_seamless", "gfs_seamless", "ecmwf_aifs025_ensemble")`, and the comment at `:2637` calls that the single source of truth. `ecmwf_ifs025` is **not** in the blend. Corroborated by the 08:46 UTC cron log, where `[OM batch]` fetches `ecmwf_ifs025` and `[ENS batch]` fetches `ecmwf_aifs025_ensemble` — two paths, two products.

**Round 2 (my correction to round 1): also wrong, and wrong the same way.** That correction claimed `weights.get(model, 1.0)` silently defaults `ecmwf_aifs025_ensemble` to 1.0, making the whole `ecmwf_w` computation dead code. **That is false.** There are TWO weight functions and I conflated them twice:

| function | line | baseline keys | ecmwf_w |
|---|---|---|---|
| `_forecast_model_weights` | **`:2123`** | `gfs_seamless`, **`ecmwf_ifs025`**, `icon_seamless` | 2.5 winter + ENSO bump |
| `_model_weights` | **`:5235`** | `icon_seamless`, `gfs_seamless`, **`ecmwf_aifs025_ensemble`** | 2.0 winter / 1.5 summer, no ENSO |

`get_ensemble_temps` calls **`_model_weights`**, whose baseline (`:5326`) *does* contain `ecmwf_aifs025_ensemble`. **There is no missing key and no dead code.** `_forecast_model_weights` is the separate deterministic daily blend. Both of my errors came from grepping a pattern, taking the first hit, and never checking which function the line sat in.

**What survives, and it is the real finding** (re-derived by the batch-88 session from `predictions.db`, 284 rows / 60 days):

- All three models genuinely resolve to `repeats = 2` today, so the effective split *is* raw member count — but the cause is **quantisation**, not a key mismatch.
- **Tier 1 (`_weights_from_mae`) fires for every city**, because per-city `n < min_n=20` for all 19 cities, so every city falls back to global MAE: `icon_seamless 1.124`, `gfs_seamless 0.834`, `ecmwf_aifs025_ensemble 1.065` (Aug) / `1.215` (Jan). `round(w*2) = 2` for all three in both seasons.
- **Therefore the `baseline` dict never applies in production, and `learned_weights.json` (tier 2) never fires at all** — tier 1 always wins. Its content is NYC-only, `icon 1.111 / gfs 0.889`, both also `repeats=2`.
- Corrected member counts: **39 / 30 / 50** (icon / gefs / aifs), not 40/31/51. `_fetch_model_ensemble` filters `k.startswith("temperature_2m_member")`, which excludes the unnumbered control series my count included. Effective split **32.8 / 25.2 / 42.0%**.

**One genuinely new defect, from the batch-88 session:** `_model_weights`' docstring at `:5303` justifies excluding `ecmwf_ifs025` on the grounds that it *"has no ensemble members"*. That is **factually false** — `ensemble-api.open-meteo.com` returns `ecmwf_ifs025_ensemble` with 50 members, verified live. The exclusion may still be correct on other grounds, but its stated reason is not, and given `ecmwf_ifs025` measures best on MAE of any member (2.138 max / 1.914 min) while the blended `ecmwf_aifs025_ensemble` measures worst on max (3.150), the reason being wrong matters.

Everything below is retained for context. **Treat its weight table and its member counts as superseded.**

## What the diagnosis found

The entry asked which of two hypotheses explained `gfs_seamless`'s outsized error. One live call to `ensemble-api.open-meteo.com` (Chicago, `models=gfs_seamless,ecmwf_ifs025,icon_seamless`, `forecast_days=7`) returned 122 temperature series:

```
ncep_gefs_seamless       30 members
ecmwf_ifs025_ensemble    50 members
icon_seamless_eps        39 members
```

**Member counts differ substantially, and the weighting code does not account for it.** `weather_markets.py` ~`:5523`:

```python
base_w = weights.get(model, 1.0)
w = 1.0 + (base_w - 1.0) * decay
repeats = max(1, round(w * 2))       # <-- quantises
all_temps.extend(temps * repeats)    # <-- per-member, not per-model
```

With the live summer weights (`gfs 1.0, ecmwf_ifs025 1.5, icon 1.0` from `_model_weights`' `baseline` dict ~`:2148`):

| model | members | w | repeats | entries | effective | **intended** |
|---|---|---|---|---|---|---|
| gfs_seamless | 30 | 1.0 | 2 | 60 | **20.8%** | 28.6% |
| ecmwf_ifs025 | 50 | 1.5 | 3 | 150 | **52.1%** | 42.9% |
| icon_seamless | 39 | 1.0 | 2 | 78 | **27.1%** | 28.6% |

## Two defects, and the second is subtler

**1. A model's influence is `weight × member_count`, but `weights` is written and documented as if it were per-model.** Right now this over-weights ECMWF and under-weights GFS — which happens to *help*, since ECMWF is the best member here. That makes it easy to leave alone and wrong to. It is not what the code intends, it silently changes if Open-Meteo alters member counts, and it worsens in winter: `ecmwf_w` rises to 2.5+ with the ENSO bump, giving `repeats=5` and ECMWF ~64%.

**2. `round(w * 2)` quantises the learned weights into half-integer steps, and does it inconsistently.** Only changes of ±0.5 in `w` have *any* effect: `w=1.0` and `w=1.2` both give `repeats=2`. Worse, Python uses banker's rounding — `round(2.5) = 2` but `round(3.5) = 4` — so `w=1.25` rounds down while `w=1.75` rounds up. **The entire per-city learned-weight path is being coarsely and asymmetrically quantised**; check `load_learned_weights()`'s real value distribution to see how much of it is being erased.

## What NOT to conclude

**Do not treat this as proof that `gfs_seamless` is a bad model.** Published 2026 verification ranks GFS **second globally** after ECMWF, ahead of or comparable to ICON. The local measurement (max: gfs 3.963 vs icon 2.020 / ecmwf 2.138 over 21 paired cells) contradicts that, which is why the entry says to suspect the pipeline. Member count alone does not explain a 2× MAE gap either — 30 vs 50 members shrinks the mean's standard error by only ~23%. **The resolution hypothesis is still open**: `ncep_gefs_seamless` is a GFS+GEFS blend documented at ~50 km, while `ecmwf_ifs025` is 0.25° (~25 km). Establish whether that accounts for the residual before touching any weight.

Also load-bearing: **MAE and Brier disagree.** On unpaired per-member Brier the ordering partly inverts — min-Brier has `gfs` **best** (0.3613) and `ecmwf_ifs025` **worst** (0.4008). Any weight decision must be made on Brier over paired cells, not the MAE table.

And n = **21** paired cells, one month, summer — far below this repo's own floors (batch 81 derived 112 for a single signal). **Fixing the weighting mechanism is justified on its own terms as a correctness defect. Re-deriving the weight VALUES is not, at this n.**

## The decision — `AskUserQuestion`

Fixing defect 1 changes live pricing on every temperature market. It currently favours the best model by accident; a correct implementation would *reduce* ECMWF's share from 52.1% to the intended 42.9% and might measurably worsen the blend. Ask: normalise per-model so declared weights mean what they say, or re-derive the declared weights against the corrected mechanism so the effective split is preserved? These give different live behaviour and the second is not simply "the safe one".

Defect 2 (quantisation) is a straightforward correctness fix — weight by fractional replication or a proper weighted mean rather than integer `repeats` — but it interacts with defect 1, so decide them together.

## Process — 29-step workflow in full

Read `C:\Users\thesa\.claude\projects\C--Users-thesa-claude-kalshi\memory\feedback_implementation_workflow.md`. No downgrade: live pricing path.

(1) Re-verify — re-run the live member-count call, it is one request and the counts are Open-Meteo's to change. (3) `AskUserQuestion` before any weight change. (7) Mutation-test via **Edit**. The key test: a model's *effective* share must equal its declared share — pin it by asserting the composition of `all_temps`, not just that a number moved. (8) Scoped: `tests/test_weather_markets.py`, `tests/test_infrastructure.py`, plus whatever `grep -rln "_model_weights\|load_learned_weights\|all_temps" tests/*.py` returns. **Never the bare full suite.** (9) Lint with `python -m pre_commit run --files <paths>` — **no git hook is installed**, so `git commit` lints nothing; add CI's own `ruff check .` / `mypy .` if you touch `audit/`. (11) Independent opus review at `effort: high`. (13) Address every finding. (14) Memory before commit. (15) Explicit confirmation before commit/push. (16) `git fetch` + rebase. (19) `python backlog_index.py`.

**Coordinate with batch 87.** It recalibrates the probabilities; this changes what goes into them. If both land, neither one's before/after measurement is interpretable in isolation — agree an order and measure between them.
